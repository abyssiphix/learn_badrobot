"""Extract the verified official CaP environment; optionally fetch official assets."""
import argparse
import ast
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

EXPECTED_COMMIT = "3ef52111c1fabc301880818f5a547570e926a76b"
ASSETS = {
    "ur5e.zip": "1Cc_fDSBL6QiDvNT4dpfAEbhbALSVoWcc",
    "robotiq_2f_85.zip": "1yOMEm-Zp_DL3nItG9RozPeJAmeOldekX",
    "bowl.zip": "1GsqNLhEl9dd4Mc3BM0dX3MibOI1FVWNM",
}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook", required=True, type=Path)
    parser.add_argument("--download-assets", action="store_true")
    args = parser.parse_args()
    source = args.notebook.expanduser().resolve()
    root = Path(__file__).resolve().parent
    commit = subprocess.check_output(
        ["git", "-C", str(source.parent), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != EXPECTED_COMMIT:
        raise RuntimeError(f"Upstream version mismatch: {commit}")
    notebook = json.loads(source.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    originals = root / "original_cells"
    originals.mkdir(exist_ok=True)
    for index, cell in enumerate(cells):
        if cell["cell_type"] == "code":
            (originals / f"cell_{index:02d}.txt").write_text(
                "".join(cell["source"]), encoding="utf-8"
            )

    text = "\n\n".join("".join(cells[i]["source"]) for i in [7, 8, 9])
    replacements = {
        "color, _, _, _, _ = env.render_image(image_size, intrinsics)":
            "color, _, _, _, _ = self.render_image(image_size, intrinsics)",
        "renderer=pybullet.ER_BULLET_HARDWARE_OPENGL":
            "renderer=pybullet.ER_TINY_RENDERER",
    }
    for before, after in replacements.items():
        if text.count(before) != 1:
            raise RuntimeError(f"Unexpected notebook source around: {before}")
        text = text.replace(before, after)
    imports = (
        "# Extracted from Google's Code as Policies Interactive_Demo.ipynb.\n"
        "# Copyright 2022 Google LLC. SPDX-License-Identifier: Apache-2.0\n"
        "# See UPSTREAM_LICENSE.txt and manifest.json for provenance and changes.\n"
        "import os\nimport threading\nfrom time import sleep\n"
        "import numpy as np\nimport pybullet\nimport pybullet_data\n\n"
    )
    module = imports + text
    ast.parse(module)
    (root / "cap_env.py").write_text(module, encoding="utf-8")
    license_text = "".join(cells[0]["source"])
    (root / "UPSTREAM_LICENSE.txt").write_text(license_text, encoding="utf-8")

    manifest = {
        "repository": "https://github.com/google-research/google-research",
        "commit": commit,
        "notebook": "code_as_policies/Interactive_Demo.ipynb",
        "notebook_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "environment_cells": [7, 8, 9],
        "changes": replacements,
        "assets": {},
    }
    assets = root / "assets"
    assets.mkdir(exist_ok=True)
    if args.download_assets:
        for filename, file_id in ASSETS.items():
            archive = assets / filename
            valid = archive.exists() and zipfile.is_zipfile(archive)
            if not valid:
                temp = assets / (filename + ".part")
                subprocess.run(
                    [sys.executable, "-m", "gdown",
                     f"https://drive.google.com/uc?id={file_id}",
                     "-O", str(temp)], check=True
                )
                if not zipfile.is_zipfile(temp):
                    raise RuntimeError(f"Not a valid ZIP file: {temp}")
                temp.replace(archive)
            with zipfile.ZipFile(archive) as zipped:
                for name in zipped.namelist():
                    target = (assets / name).resolve()
                    if not target.is_relative_to(assets.resolve()):
                        raise RuntimeError(f"Invalid archive path: {name}")
                zipped.extractall(assets)
            manifest["assets"][filename] = {
                "google_drive_id": file_id,
                "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            }
        for relative in ["ur5e/ur5e.urdf", "robotiq_2f_85/robotiq_2f_85.urdf", "bowl/bowl.urdf"]:
            if not (assets / relative).is_file():
                raise RuntimeError(f"Asset missing after extraction: {relative}")
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Environment extraction complete:", root / "cap_env.py")
    print("Original cells:", originals)
    if args.download_assets:
        print("All three official asset packages downloaded and verified as ZIP files.")
    else:
        print("Assets not downloaded; use --download-assets before the scene check.")

if __name__ == "__main__":
    main()
