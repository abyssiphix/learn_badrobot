"""Load one official CaP scene and save images, without calling an LLM."""
import json
import os
from pathlib import Path

import numpy as np
import pybullet
from PIL import Image

from cap_env import PickPlaceEnv

def main():
    root = Path(__file__).resolve().parent
    assets = root / "assets"
    for relative in ["ur5e/ur5e.urdf", "robotiq_2f_85/robotiq_2f_85.urdf", "bowl/bowl.urdf"]:
        if not (assets / relative).is_file():
            raise FileNotFoundError(f"Missing asset: {assets / relative}")
    output = root / "outputs" / "scene_check"
    output.mkdir(parents=True, exist_ok=True)
    old_cwd = Path.cwd()
    os.chdir(assets)
    np.random.seed(0)
    env = None
    try:
        env = PickPlaceEnv(render=False)
        objects = ["red block", "yellow bowl"]
        observation = env.reset(objects)
        color = env.get_camera_image()
        Image.fromarray(color).save(output / "official_scene.png")
        Image.fromarray(observation["image"]).save(output / "heightmap.png")
        positions = {name: env.get_obj_pos(name).tolist() for name in objects}
        (output / "positions.json").write_text(
            json.dumps(positions, indent=2), encoding="utf-8"
        )
        for name, position in positions.items():
            print(name, np.round(position, 4))
        print("Scene loaded. Image:", output / "official_scene.png")
        print("Top-down observation:", output / "heightmap.png")
    finally:
        if pybullet.isConnected():
            pybullet.disconnect()
        if env is not None and env.gripper is not None:
            env.gripper.constraints_thread.join(timeout=2)
        os.chdir(old_cwd)

if __name__ == "__main__":
    main()
