"""Render the example peak-value cloud."""

from __future__ import annotations

import sys
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from kinematic_word_cloud.data import load_keyframes
from kinematic_word_cloud.render import render_peak_cloud


def main() -> None:
    table = load_keyframes(PROJECT_ROOT / "examples" / "simple_keyframes.csv")
    render_peak_cloud(
        table,
        PROJECT_ROOT / "output" / "starting_cloud.png",
        width=1200,
        height=800,
        random_state=7,
    )
    print("Wrote output/starting_cloud.png")


if __name__ == "__main__":
    main()
