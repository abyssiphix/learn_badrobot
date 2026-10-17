"""Check the extracted official CaP pick/place primitive without an LLM.

Place beside cap_env.py in the remote cap-adapt directory.
"""
import json
import os
import signal
from datetime import datetime
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import pybullet
from PIL import Image

from cap_env import PickPlaceEnv


def timeout_handler(signum, frame):
    raise TimeoutError("Scene setup or motion exceeded 180 seconds; inspect saved frames.")


def main():
    root = Path(__file__).resolve().parent
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = root / "outputs" / f"official_pick_place_{run_id}"
    output.mkdir(parents=True)
    record = {
        "experiment": "official primitive check, no LLM",
        "objects": ["red block", "yellow bowl"],
        "seed": 0,
        "status": "running",
        "video_renderer": "TinyRenderer",
        "note": "Success uses the upstream proximity/height heuristic, not exact bowl containment.",
    }
    previous_cwd = Path.cwd()
    env = None
    max_height = None
    timestep = None
    previous_handler = signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(180)
    try:
        os.chdir(root / "assets")
        np.random.seed(record["seed"])
        env = PickPlaceEnv(render=True, high_res=True, high_frame_rate=False)
        env.reset(record["objects"])
        # Explicitly use the timestep declared by the upstream environment.
        pybullet.setTimeStep(env.dt)
        timestep = pybullet.getPhysicsEngineParameters()["fixedTimeStep"]
        record["physics_timestep_seconds"] = timestep
        before = {name: env.get_obj_pos(name).tolist() for name in record["objects"]}
        record["before"] = before
        initial_height = before["red block"][2]
        max_height = initial_height
        Image.fromarray(env.get_camera_image()).save(output / "before.png")

        # Observe actual block height without changing the upstream action primitive.
        original_step = env.step_sim_and_render

        def observed_step():
            nonlocal max_height
            original_step()
            max_height = max(max_height, float(env.get_obj_pos("red block")[2]))

        env.step_sim_and_render = observed_step
        print("Running official primitive: red block -> yellow bowl", flush=True)
        env.step({
            "pick": env.get_obj_pos("red block")[:2],
            "place": env.get_obj_pos("yellow bowl")[:2],
        })
        # Observe settling for one more simulated second.
        for _ in range(round(1 / timestep)):
            env.step_sim_and_render()

        after = {name: env.get_obj_pos(name).tolist() for name in record["objects"]}
        distance = float(np.linalg.norm(
            np.array(after["red block"][:2]) - np.array(after["yellow bowl"][:2])
        ))
        upstream_ok = bool(env.on_top_of("red block", "yellow bowl"))
        lifted = bool(max_height > initial_height + 0.03)
        record.update({
            "after": after,
            "xy_distance_to_bowl_mm": distance * 1000,
            "maximum_block_height_m": max_height,
            "lift_above_initial_mm": (max_height - initial_height) * 1000,
            "lifted_over_3cm": lifted,
            "upstream_on_top_of": upstream_ok,
            "status": "passed" if upstream_ok and lifted else "failed",
        })
        Image.fromarray(env.get_camera_image()).save(output / "after.png")
        print(f"Distance to bowl center: {distance * 1000:.1f} mm")
        print(f"Maximum lift: {(max_height - initial_height) * 1000:.1f} mm")
        print(f"Upstream on_top_of: {upstream_ok}")
        print(f"Check status: {record['status']}")
    except Exception as error:
        record["status"] = "error"
        record["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        frames = list(env.cache_video) if env is not None and hasattr(env, "cache_video") else []
        if pybullet.isConnected():
            pybullet.disconnect()
        if env is not None and env.gripper is not None:
            env.gripper.constraints_thread.join(timeout=2)
        os.chdir(previous_cwd)
        if frames and timestep:
            # Upstream low-rate capture records one frame per 60 physics steps.
            fps = 1 / (60 * timestep)
            record["video_fps"] = fps
            record["video_frame_count"] = len(frames)
            try:
                with imageio.get_writer(
                    str(output / "pick_place.mp4"), fps=fps,
                    codec="libx264", macro_block_size=1,
                ) as writer:
                    for image in frames:
                        writer.append_data(np.asarray(image, dtype=np.uint8))
            except Exception as error:
                record["video_error"] = str(error)
                print("Video export failed:", error)
        (output / "result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("Results:", output, flush=True)


if __name__ == "__main__":
    main()
