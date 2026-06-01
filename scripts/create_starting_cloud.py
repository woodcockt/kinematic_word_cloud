"""Render the example peak-value cloud."""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from kinematic_word_cloud.config import (
    ASPECT_CHOICES,
    DEFAULT_ASPECT,
    resolve_canvas_size,
)
from kinematic_word_cloud.data import load_keyframes
from kinematic_word_cloud.render import render_peak_cloud


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "examples" / "simple_keyframes.csv",
        help="Path to a wide keyframe CSV.",
    )
    parser.add_argument(
        "--aspect",
        choices=ASPECT_CHOICES,
        default=DEFAULT_ASPECT,
        help="Canvas aspect-ratio preset.",
    )
    args = parser.parse_args()

    input_path = args.input
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    table = load_keyframes(input_path)
    canvas_size = resolve_canvas_size(args.aspect)
    render_peak_cloud(
        table,
        PROJECT_ROOT / "output" / "starting_cloud.png",
        width=canvas_size.width,
        height=canvas_size.height,
        random_state=7,
    )
    print(
        "Wrote output/starting_cloud.png "
        f"({canvas_size.width}x{canvas_size.height}, {args.aspect})"
    )


if __name__ == "__main__":
    main()
