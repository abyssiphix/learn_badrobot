"""Extract official LMP classes, prompts, config and wrapper from a pinned notebook."""
import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

COMMIT = "3ef52111c1fabc301880818f5a547570e926a76b"
CELL_IDS = [5, 12, 14, 15, 16, 17, 18, 19, 21, 23]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook", required=True, type=Path)
    args = parser.parse_args()
    source = args.notebook.expanduser().resolve()
    commit = subprocess.check_output(
        ["git", "-C", str(source.parent), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != COMMIT:
        raise RuntimeError(f"Unexpected upstream commit: {commit}")
    notebook = json.loads(source.read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parent
    originals = root / "original_lmp_cells"
    originals.mkdir(exist_ok=True)
    parts = []
    cell_hashes = {}
    for index in CELL_IDS:
        text = "".join(notebook["cells"][index]["source"])
        (originals / f"cell_{index:02d}.txt").write_text(text, encoding="utf-8")
        cell_hashes[str(index)] = hashlib.sha256(text.encode()).hexdigest()
        if index == 5:
            before = "print('Retrying after 10s.')\n                sleep(10)"
            if text.count(before) != 2:
                raise RuntimeError("Unexpected API retry code; stop before extraction.")
            text = text.replace(before, "raise  # Fail fast; adapter saves the API error.")
        parts.append(text)
    header = '''# Copyright 2022 Google LLC. SPDX-License-Identifier: Apache-2.0
# Extracted official Code as Policies LMP code; see lmp_manifest.json.
import ast
import copy
from time import sleep
from types import SimpleNamespace
import numpy as np
import astunparse
import shapely
import shapely.geometry
import shapely.affinity
from shapely.geometry import *
from shapely.affinity import *
from pygments import highlight
from pygments.lexers import PythonLexer
from pygments.formatters import TerminalFormatter
from openai import RateLimitError, APIConnectionError
from cap_env import COLORS

model_name = "deepseek-flash"
openai = None

def configure_backend(backend):
    global openai
    openai = SimpleNamespace(
        Completion=SimpleNamespace(create=backend.create),
        Edit=SimpleNamespace(create=backend.edit),
    )

'''
    module = header + "\n\n".join(parts) + "\n"
    ast.parse(module)
    (root / "cap_lmp.py").write_text(module, encoding="utf-8")
    (root / "LMP_UPSTREAM_LICENSE.txt").write_text(
        "".join(notebook["cells"][0]["source"]), encoding="utf-8"
    )
    manifest = {
        "repository": "https://github.com/google-research/google-research",
        "commit": commit, "cells": CELL_IDS, "cell_sha256": cell_hashes,
        "notebook_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "changes": [
            "Import the extracted cap_env.COLORS; replace Colab setup with module imports.",
            "Inject a legacy Completion facade backed by DeepSeek chat completions.",
            "Add a chat system instruction requesting only a Python continuation.",
            "Keep original few-shot prompt strings, LMP classes, wrapper and config values.",
            "Replace unbounded retry sleeps on API errors with immediate re-raise.",
            "Select model at runtime; disable legacy automatic Edit calls.",
            "Strip a complete Markdown fence, logging raw and cleaned output separately.",
        ],
        "warning": "The original exec_safe helper is not a security sandbox.",
    }
    (root / "lmp_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Official LMP extraction complete:", root / "cap_lmp.py")
    print("Preserved prompt cells: 14 through 19; provenance: lmp_manifest.json")


if __name__ == "__main__":
    main()
