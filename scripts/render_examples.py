"""Render compact gallery previews for the README."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from kinematic_word_cloud.config import resolve_animation_timing
from kinematic_word_cloud.data import load_keyframes
from kinematic_word_cloud.export import export_gif
from kinematic_word_cloud.labels import LabelConfig
from kinematic_word_cloud.layout import COLOR_PALETTES, ColorOptions
from kinematic_word_cloud.render import render_fixed_animation_frames


RENDER_DIR = PROJECT_ROOT / "examples" / "renders"
LANDSCAPE_SIZE = (480, 270)
VERTICAL_SIZE = (270, 480)
FPS = 8


@dataclass(frozen=True)
class ExampleRender:
    """Configuration for one generated preview GIF."""

    name: str
    input_path: str
    width: int
    height: int
    frames_per_transition: int
    use_physics: bool = False
    interpolation: str = "linear"
    color_options: ColorOptions | None = None
    label_config: LabelConfig | None = None
    random_state: int = 7


def main() -> None:
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    for old_gif in RENDER_DIR.glob("*.gif"):
        old_gif.unlink()

    examples = _examples()
    with tempfile.TemporaryDirectory(prefix="kwc_examples_") as temp_root:
        temp_path = Path(temp_root)
        for example in examples:
            _render_example(example, temp_path / example.name)

    print(f"Wrote {len(examples)} preview GIFs to {RENDER_DIR.relative_to(PROJECT_ROOT)}")


def _examples() -> list[ExampleRender]:
    color_table = "examples/color_modes_keyframes.csv"
    simple_table = "examples/simple_keyframes.csv"
    bioit_table = "examples/bioit_top_terms_2016_2026.csv"
    landscape_width, landscape_height = LANDSCAPE_SIZE
    vertical_width, vertical_height = VERTICAL_SIZE
    label = LabelConfig(
        mode="keyframe",
        position="top-right",
        font_size=22,
        color="#222222",
        opacity=0.85,
        margin=14,
    )

    return [
        ExampleRender(
            name="simple_fixed",
            input_path=simple_table,
            width=landscape_width,
            height=landscape_height,
            frames_per_transition=6,
            color_options=ColorOptions(color_by="group"),
        ),
        ExampleRender(
            name="simple_physics",
            input_path=simple_table,
            width=landscape_width,
            height=landscape_height,
            frames_per_transition=6,
            use_physics=True,
            color_options=ColorOptions(color_by="group"),
        ),
        ExampleRender(
            name="color_single",
            input_path=color_table,
            width=landscape_width,
            height=landscape_height,
            frames_per_transition=6,
            color_options=ColorOptions(color_by="single", default_color="#344055"),
        ),
        ExampleRender(
            name="color_group",
            input_path=color_table,
            width=landscape_width,
            height=landscape_height,
            frames_per_transition=6,
            color_options=ColorOptions(
                palette=COLOR_PALETTES["okabe-ito"],
                color_by="group",
                group_colors={
                    "design": "#2A9D8F",
                    "language": "#0072B2",
                    "motion": "#4A2C7A",
                },
            ),
        ),
        ExampleRender(
            name="color_word",
            input_path=color_table,
            width=landscape_width,
            height=landscape_height,
            frames_per_transition=6,
            color_options=ColorOptions(
                palette=COLOR_PALETTES["tableau"],
                color_by="word",
            ),
        ),
        ExampleRender(
            name="interpolation_linear",
            input_path=color_table,
            width=landscape_width,
            height=landscape_height,
            frames_per_transition=8,
            interpolation="linear",
            color_options=ColorOptions(color_by="single", default_color="#2A9D8F"),
        ),
        ExampleRender(
            name="interpolation_smoothstep",
            input_path=color_table,
            width=landscape_width,
            height=landscape_height,
            frames_per_transition=8,
            interpolation="smoothstep",
            color_options=ColorOptions(color_by="single", default_color="#2A9D8F"),
        ),
        ExampleRender(
            name="bioit_vertical",
            input_path=bioit_table,
            width=vertical_width,
            height=vertical_height,
            frames_per_transition=2,
            interpolation="smoothstep",
            color_options=ColorOptions(
                palette=COLOR_PALETTES["okabe-ito"],
                color_by="group",
                group_colors={
                    "2-gram": "#0072B2",
                    "3-gram": "#009E73",
                    "4-gram": "#D55E00",
                },
            ),
            label_config=label,
        ),
    ]


def _render_example(example: ExampleRender, frame_dir: Path) -> None:
    table = load_keyframes(PROJECT_ROOT / example.input_path)
    timing = resolve_animation_timing(
        table,
        frames_per_transition=example.frames_per_transition,
        fps=FPS,
    )
    frame_paths = render_fixed_animation_frames(
        table,
        frame_dir,
        frames_per_transition=timing.frames_per_transition,
        width=example.width,
        height=example.height,
        random_state=example.random_state,
        use_physics=example.use_physics,
        label_config=example.label_config,
        interpolation=example.interpolation,
        color_options=example.color_options,
    )
    output_path = RENDER_DIR / f"{example.name}.gif"
    export_gif(frame_paths, output_path, fps=timing.fps)
    print(f"Wrote {output_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
