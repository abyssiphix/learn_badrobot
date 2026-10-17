"""Run one normal instruction through official CaP LMPs and the extracted simulator."""
import argparse
import hashlib
import json
import os
import signal
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime
from getpass import getpass
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import pybullet
from PIL import Image

import cap_lmp
from cap_env import PickPlaceEnv
from deepseek_backend import Backend


class Tee:
    def __init__(self, console, file):
        self.console, self.file = console, file
    def write(self, value):
        self.console.write(value)
        self.file.write(value)
        return len(value)
    def flush(self):
        self.console.flush()
        self.file.flush()


def timed_out(signum, frame):
    raise TimeoutError("Total run exceeded the configured time limit.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--instruction", default="put the red block on the yellow bowl")
    parser.add_argument("--model", default="deepseek-flash")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    if args.max_calls < 1 or args.timeout < 1:
        parser.error("--max-calls and --timeout must be positive")
    api_key = os.environ.get("DEEPSEEK_API_KEY") or getpass("DeepSeek API key (hidden): ").strip()
    if not api_key:
        raise ValueError("API key is empty")
    root = Path(__file__).resolve().parent
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True)
    record = {
        "instruction": args.instruction, "model": args.model,
        "seed": args.seed, "max_api_calls": args.max_calls,
        "objects": ["red block", "yellow bowl"],
        "evaluation_target": "red block on yellow bowl",
        "status": "running", "action_calls": [],
        "note": "Normal-task baseline with a changed model/API/renderer; not BadRobot attack results.",
    }
    for name in ["cap_env.py", "cap_lmp.py", "deepseek_backend.py", Path(__file__).name]:
        record.setdefault("source_sha256", {})[name] = hashlib.sha256((root / name).read_bytes()).hexdigest()
    for name in ["manifest.json", "lmp_manifest.json"]:
        if (root / name).exists():
            record[name] = json.loads((root / name).read_text(encoding="utf-8"))
    backend = Backend(api_key, output / "api_calls", model=args.model, max_calls=args.max_calls)
    del api_key
    cap_lmp.configure_backend(backend)
    env = None
    frames = []
    timestep = None
    max_z = None
    old_cwd = Path.cwd()
    old_handler = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(args.timeout)
    started = time.monotonic()
    try:
        os.chdir(root / "assets")
        np.random.seed(args.seed)
        env = PickPlaceEnv(render=True, high_res=True, high_frame_rate=False)
        env.reset(record["objects"])
        pybullet.setTimeStep(env.dt)
        timestep = pybullet.getPhysicsEngineParameters()["fixedTimeStep"]
        initial = {name: env.get_obj_pos(name).tolist() for name in record["objects"]}
        record["before"] = initial
        max_z = initial["red block"][2]
        Image.fromarray(env.get_camera_image()).save(output / "before.png")
        original_tick, original_action = env.step_sim_and_render, env.step

        def tick():
            nonlocal max_z
            original_tick()
            max_z = max(max_z, float(env.get_obj_pos("red block")[2]))

        def action(action=None):
            entry = {
                "pick": np.asarray(action["pick"]).tolist(),
                "place": np.asarray(action["place"]).tolist(),
                "status": "started",
            }
            record["action_calls"].append(entry)
            result = original_action(action)
            entry["status"] = "completed"
            return result

        env.step_sim_and_render = tick
        env.step = action
        cfg = cap_lmp.copy.deepcopy(cap_lmp.cfg_tabletop)
        for item in cfg["lmps"].values():
            item["engine"] = args.model
        record["lmp_config"] = cfg
        policy = cap_lmp.setup_LMP(env, cfg)
        with (output / "execution.log").open("w", encoding="utf-8") as log:
            with redirect_stdout(Tee(sys.stdout, log)):
                print("Instruction:", args.instruction, flush=True)
                policy(args.instruction, f"objects = {env.object_list}")
        for _ in range(round(1 / timestep)):
            env.step_sim_and_render()
        final = {name: env.get_obj_pos(name).tolist() for name in record["objects"]}
        distance = float(np.linalg.norm(np.array(final["red block"][:2]) - np.array(final["yellow bowl"][:2])))
        lifted = bool(max_z > initial["red block"][2] + 0.03)
        on_top = bool(env.on_top_of("red block", "yellow bowl"))
        completed = any(x["status"] == "completed" for x in record["action_calls"])
        record.update({
            "after": final, "xy_distance_to_bowl_mm": distance * 1000,
            "lift_above_initial_mm": (max_z - initial["red block"][2]) * 1000,
            "upstream_on_top_of": on_top,
            "status": "passed" if lifted and on_top and completed else "failed",
        })
        Image.fromarray(env.get_camera_image()).save(output / "after.png")
        print(f"Distance to bowl center: {distance * 1000:.1f} mm")
        print(f"Upstream on_top_of: {on_top}")
        print(f"Action calls: {len(record['action_calls'])}")
        print(f"Check status: {record['status']}")
    except Exception as error:
        record["status"] = "error"
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        if env is not None:
            frames = list(getattr(env, "cache_video", []))
        if pybullet.isConnected():
            pybullet.disconnect()
        if env is not None and env.gripper is not None:
            env.gripper.constraints_thread.join(timeout=2)
        os.chdir(old_cwd)
        record["api_calls"] = backend.calls
        record["elapsed_wall_seconds"] = time.monotonic() - started
        record["physics_timestep_seconds"] = timestep
        if frames and timestep:
            fps = 1 / (60 * timestep)
            record["video_fps"] = fps
            try:
                with imageio.get_writer(str(output / "pick_place.mp4"), fps=fps,
                                        codec="libx264", macro_block_size=1) as writer:
                    for frame in frames:
                        writer.append_data(np.asarray(frame, dtype=np.uint8))
            except Exception as error:
                record["video_error"] = str(error)
                print("Video export failed:", error)
        (output / "result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"API calls: {backend.calls}")
        print("Results:", output, flush=True)


if __name__ == "__main__":
    main()
