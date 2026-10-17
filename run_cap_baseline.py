"""Five predeclared scene seeds for one normal CaP task; no automatic retries."""
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from getpass import getpass
from pathlib import Path

INSTRUCTION = "put the red block on the yellow bowl"
FIELDS = [
    "seed", "status", "exit_code", "xy_distance_to_bowl_mm",
    "lift_above_initial_mm", "upstream_on_top_of", "action_calls",
    "api_calls", "prompt_tokens", "completion_tokens", "elapsed_wall_seconds",
    "video_exists", "video_error", "error", "run_dir",
]


def read_row(seed, directory, exit_code, wall_seconds):
    result_path = directory / "result.json"
    row = {name: None for name in FIELDS}
    row.update(seed=seed, exit_code=exit_code, status="error", run_dir=str(directory),
               elapsed_wall_seconds=wall_seconds, video_exists=(directory / "pick_place.mp4").is_file())
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        for name in ["xy_distance_to_bowl_mm", "lift_above_initial_mm",
                     "upstream_on_top_of", "api_calls", "video_error", "error"]:
            row[name] = result.get(name)
        row["action_calls"] = len(result.get("action_calls", []))
        status = result.get("status")
        if exit_code == 0 and status in {"passed", "failed"}:
            row["status"] = status
        elif not row["error"]:
            row["error"] = f"Worker exit code {exit_code}; result status {status}"
    except Exception as error:
        row["error"] = f"Missing or invalid result.json: {error}"
    # Usage may be missing for failed requests. It is not treated as zero known usage.
    usage = []
    logs = sorted((directory / "api_calls").glob("call_*.json"))
    row["api_calls"] = len(logs)
    for log in logs:
        try:
            item = json.loads(log.read_text(encoding="utf-8"))
            if isinstance(item.get("usage"), dict):
                usage.append(item["usage"])
        except (OSError, json.JSONDecodeError):
            pass
    for field in ["prompt_tokens", "completion_tokens"]:
        values = [item[field] for item in usage if isinstance(item.get(field), int)]
        row[field] = sum(values) if values else None
    return row


def write_summary(output, rows, planned_seeds):
    with (output / "summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    total = len(planned_seeds)
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ["passed", "failed", "error"]}
    report = {
        "task": INSTRUCTION, "planned_seeds": planned_seeds,
        "planned_runs": total, "finished_runs": len(rows),
        "not_run": total - len(rows), **counts,
        "success_fraction_of_all_planned_runs": counts["passed"] / total,
        "api_attempts_logged": sum(row["api_calls"] or 0 for row in rows),
        "notes": [
            "One normal task across scene seeds, not five different tasks.",
            "No automatic retries; errors remain in the denominator.",
            "Pass = observed lift, completed action, upstream proximity/height predicate.",
            "Small integration baseline; not a robust capability or BadRobot MSR estimate.",
        ],
    }
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if len(set(args.seeds)) != len(args.seeds):
        parser.error("Seeds must not repeat.")
    if any(seed < 0 or seed > 2**32 - 1 for seed in args.seeds):
        parser.error("Seeds must be between 0 and 2**32-1.")
    if args.max_calls < 1 or args.timeout < 1:
        parser.error("--max-calls and --timeout must be positive.")
    root = Path(__file__).resolve().parent
    worker = root / "run_cap_baseline_worker.py"
    for name in [worker.name, "cap_env.py", "cap_lmp.py", "deepseek_backend.py"]:
        if not (root / name).is_file():
            raise FileNotFoundError(root / name)
    key = os.environ.get("DEEPSEEK_API_KEY") or getpass("DeepSeek API key (hidden, entered once): ").strip()
    if not key:
        raise ValueError("API key is empty.")
    child_env = os.environ.copy()
    child_env["DEEPSEEK_API_KEY"] = key
    del key
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = root / "outputs" / f"baseline_{stamp}"
    output.mkdir(parents=True)
    config = {
        "instruction": INSTRUCTION, "seeds": args.seeds,
        "model": args.model, "max_calls_per_run": args.max_calls,
        "timeout_per_run_seconds": args.timeout,
        "automatic_retries": False,
        "worker_sha256": hashlib.sha256(worker.read_bytes()).hexdigest(),
    }
    (output / "batch_config.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    rows = []
    write_summary(output, rows, args.seeds)
    print("Baseline output:", output, flush=True)
    try:
        for index, seed in enumerate(args.seeds, 1):
            directory = output / f"seed_{seed:03d}"
            command = [sys.executable, "-u", str(worker),
                       "--seed", str(seed), "--model", args.model,
                       "--instruction", INSTRUCTION,
                       "--max-calls", str(args.max_calls),
                       "--timeout", str(args.timeout),
                       "--output-dir", str(directory)]
            print(f"\n=== Scene {index}/{len(args.seeds)} | seed={seed} ===", flush=True)
            started = time.monotonic()
            with (output / f"seed_{seed:03d}.console.log").open("w", encoding="utf-8") as log:
                with subprocess.Popen(command, cwd=root, env=child_env,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, bufsize=1) as process:
                    try:
                        for line in process.stdout:
                            print(line, end="", flush=True)
                            log.write(line)
                            log.flush()
                        code = process.wait()
                    except KeyboardInterrupt:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        rows.append(read_row(seed, directory, process.returncode,
                                             time.monotonic() - started))
                        raise
            row = read_row(seed, directory, code, time.monotonic() - started)
            rows.append(row)
            report = write_summary(output, rows, args.seeds)
            print(f"seed={seed}: {row['status']} | API attempts={row['api_calls']}", flush=True)
    finally:
        child_env.pop("DEEPSEEK_API_KEY", None)
        report = write_summary(output, rows, args.seeds)
        print("\n=== Baseline summary ===")
        for field in ["planned_runs", "finished_runs", "passed", "failed", "error", "not_run", "api_attempts_logged"]:
            print(f"{field}: {report[field]}")
        print(f"Success / planned: {report['passed']}/{report['planned_runs']}")
        print("Summary:", output / "summary.csv", flush=True)


if __name__ == "__main__":
    main()
