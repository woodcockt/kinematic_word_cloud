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
from kinematic_word_cloud.render import render_fixed_animation_frames


def main() -> None:
    parser = argparse.ArgumentParser()
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
    args = parser.parse_args()

    table = load_keyframes(PROJECT_ROOT / "examples" / "simple_keyframes.csv")
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
        )
        print(f"Wrote {svg_path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
