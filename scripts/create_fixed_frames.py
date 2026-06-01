"""Render fixed-position animation frames from the example keyframes."""

from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from kinematic_word_cloud.config import DEFAULT_FPS, resolve_animation_timing
from kinematic_word_cloud.data import KeyframeDataError, load_keyframes
from kinematic_word_cloud.export import export_gif, export_mp4, export_svg
from kinematic_word_cloud.labels import LABEL_MODES, LABEL_POSITIONS, LabelConfig
from kinematic_word_cloud.render import render_fixed_animation_frames


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "examples" / "simple_keyframes.csv",
        help="Path to a wide keyframe CSV.",
    )
    parser.add_argument(
        "--physics",
        action="store_true",
        help="Enable the lightweight spring-and-collision solver.",
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        help="Export the rendered frames to an animated GIF.",
    )
    parser.add_argument(
        "--mp4",
        action="store_true",
        help="Export the rendered frames to an MP4 file using ffmpeg.",
    )
    parser.add_argument(
        "--svg",
        action="store_true",
        help="Export the animation to sampled animated SVG.",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=None,
        help=(
            "Playback/export frame rate, or target frame rate with duration "
            f"options. Defaults to {DEFAULT_FPS:g}."
        ),
    )
    parser.add_argument(
        "--total-duration",
        type=float,
        default=None,
        help="Total animation length in seconds. Calculates frames from target FPS.",
    )
    parser.add_argument(
        "--seconds-per-transition",
        "--transition-duration",
        type=float,
        default=None,
        help="Seconds between adjacent keyframes. Calculates frames from target FPS.",
    )
    parser.add_argument(
        "--frames-per-transition",
        type=int,
        default=None,
        help="Number of rendered frames between adjacent keyframes.",
    )
    parser.add_argument(
        "--label-mode",
        choices=LABEL_MODES,
        default="none",
        help="Overlay label mode.",
    )
    parser.add_argument(
        "--label-position",
        choices=LABEL_POSITIONS,
        default="top-left",
        help="Overlay label position.",
    )
    parser.add_argument(
        "--label-size",
        type=int,
        default=56,
        help="Overlay label font size.",
    )
    parser.add_argument(
        "--label-color",
        default="#222222",
        help="Overlay label CSS/Pillow color.",
    )
    parser.add_argument(
        "--label-opacity",
        type=float,
        default=0.85,
        help="Overlay label opacity from 0 to 1.",
    )
    parser.add_argument(
        "--label-margin",
        type=int,
        default=32,
        help="Overlay label margin in pixels.",
    )
    args = parser.parse_args()

    input_path = args.input
    if not input_path.is_absolute():
        input_path = PROJECT_ROOT / input_path
    table = load_keyframes(input_path)
    try:
        timing = resolve_animation_timing(
            table,
            frames_per_transition=args.frames_per_transition,
            fps=args.fps,
            total_duration_seconds=args.total_duration,
            seconds_per_transition=args.seconds_per_transition,
        )
    except KeyframeDataError as exc:
        parser.error(str(exc))
    label_config = _build_label_config(args, parser)
    output_dir = PROJECT_ROOT / "output" / (
        "physics_frames" if args.physics else "fixed_frames"
    )
    frame_paths = render_fixed_animation_frames(
        table,
        output_dir,
        frames_per_transition=timing.frames_per_transition,
        width=1200,
        height=800,
        random_state=7,
        use_physics=args.physics,
        label_config=label_config,
    )
    relative_output_dir = output_dir.relative_to(PROJECT_ROOT)
    print(f"Wrote {len(frame_paths)} frames to {relative_output_dir}")
    target_fps = (
        f", target {timing.target_fps:.3f} fps"
        if abs(timing.fps - timing.target_fps) > 0.001
        else ""
    )
    print(
        "Timing: "
        f"{timing.duration_seconds:.3f}s total, "
        f"{timing.seconds_per_transition:.3f}s/transition, "
        f"{timing.frame_count} frames, "
        f"{timing.frames_per_transition} frames/transition, "
        f"{timing.fps:.3f} fps"
        f"{target_fps}"
    )

    output_name = "physics_animation" if args.physics else "fixed_animation"
    if args.gif:
        gif_path = export_gif(
            frame_paths,
            PROJECT_ROOT / "output" / f"{output_name}.gif",
            fps=timing.fps,
        )
        print(f"Wrote {gif_path.relative_to(PROJECT_ROOT)}")

    if args.mp4:
        mp4_path = export_mp4(
            frame_paths,
            PROJECT_ROOT / "output" / f"{output_name}.mp4",
            fps=timing.fps,
        )
        print(f"Wrote {mp4_path.relative_to(PROJECT_ROOT)}")

    if args.svg:
        svg_path = export_svg(
            table,
            PROJECT_ROOT / "output" / f"{output_name}.svg",
            frames_per_transition=timing.frames_per_transition,
            fps=timing.fps,
            duration_seconds=timing.duration_seconds,
            width=1200,
            height=800,
            random_state=7,
            use_physics=args.physics,
            label_config=label_config,
        )
        print(f"Wrote {svg_path.relative_to(PROJECT_ROOT)}")


def _build_label_config(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> LabelConfig | None:
    if args.label_mode == "none":
        return None
    if args.label_size <= 0:
        parser.error("--label-size must be greater than zero.")
    if args.label_margin < 0:
        parser.error("--label-margin must be non-negative.")
    if not 0 <= args.label_opacity <= 1:
        parser.error("--label-opacity must be between 0 and 1.")

    return LabelConfig(
        mode=args.label_mode,
        position=args.label_position,
        font_size=args.label_size,
        color=args.label_color,
        opacity=args.label_opacity,
        margin=args.label_margin,
    )


if __name__ == "__main__":
    main()
