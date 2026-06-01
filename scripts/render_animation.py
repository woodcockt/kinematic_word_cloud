"""Render keyframe word-cloud animations and optional exports."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = PROJECT_ROOT / ".cache"
os.environ.setdefault("MPLCONFIGDIR", str(CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(CACHE_ROOT))

sys.path.insert(0, str(PROJECT_ROOT / "src"))

from kinematic_word_cloud.config import (
    ASPECT_CHOICES,
    DEFAULT_ASPECT,
    DEFAULT_FPS,
    resolve_animation_timing,
    resolve_canvas_size,
)
from kinematic_word_cloud.data import KeyframeDataError, load_keyframes
from kinematic_word_cloud.export import export_gif, export_mp4, export_svg
from kinematic_word_cloud.labels import LABEL_MODES, LABEL_POSITIONS
from kinematic_word_cloud.layout import COLOR_BY_MODES, COLOR_PALETTES
from kinematic_word_cloud.render_config import (
    build_label_config,
    display_path,
    load_render_config,
    optional_bool,
    resolve_color_options,
    resolve_export_formats,
    resolve_export_paths,
    resolve_interpolation,
    resolve_project_path,
    resolve_timing_values,
    setting,
)
from kinematic_word_cloud.render import render_fixed_animation_frames
from kinematic_word_cloud.timeline import INTERPOLATION_MODES


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a TOML render configuration file.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=argparse.SUPPRESS,
        help="Path to a wide keyframe CSV.",
    )
    parser.add_argument(
        "--aspect",
        choices=ASPECT_CHOICES,
        default=argparse.SUPPRESS,
        help="Canvas aspect-ratio preset.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=argparse.SUPPRESS,
        help="Directory for rendered PNG frame sequences.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=argparse.SUPPRESS,
        help=(
            "Animation output file path. With multiple export formats, this is "
            "used as a filename stem."
        ),
    )
    parser.add_argument(
        "--physics",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable the lightweight spring-and-collision solver.",
    )
    parser.add_argument(
        "--exports",
        nargs="+",
        default=argparse.SUPPRESS,
        metavar="FORMAT",
        help=(
            "Animation export formats: gif, mp4, svg. Accepts space- or "
            "comma-separated values."
        ),
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=argparse.SUPPRESS,
        help=(
            "Playback/export frame rate, or target frame rate with duration "
            f"options. Defaults to {DEFAULT_FPS:g}."
        ),
    )
    parser.add_argument(
        "--total-duration",
        type=float,
        default=argparse.SUPPRESS,
        help="Total animation length in seconds. Calculates frames from target FPS.",
    )
    parser.add_argument(
        "--seconds-per-transition",
        "--transition-duration",
        type=float,
        default=argparse.SUPPRESS,
        help="Seconds between adjacent keyframes. Calculates frames from target FPS.",
    )
    parser.add_argument(
        "--frames-per-transition",
        type=int,
        default=argparse.SUPPRESS,
        help="Number of rendered frames between adjacent keyframes.",
    )
    parser.add_argument(
        "--interpolation",
        choices=INTERPOLATION_MODES,
        default=argparse.SUPPRESS,
        help="Value interpolation curve between adjacent keyframes.",
    )
    parser.add_argument(
        "--palette",
        choices=tuple(COLOR_PALETTES),
        default=argparse.SUPPRESS,
        help="Named palette for deterministic word or group colors.",
    )
    parser.add_argument(
        "--palette-file",
        type=Path,
        default=argparse.SUPPRESS,
        help="Path to a text, .hex, or GIMP .gpl palette file.",
    )
    parser.add_argument(
        "--color-by",
        choices=COLOR_BY_MODES,
        default=argparse.SUPPRESS,
        help="How to color words without explicit spreadsheet colors.",
    )
    parser.add_argument(
        "--default-color",
        default=argparse.SUPPRESS,
        help="Fallback hex color used when --color-by single.",
    )
    parser.add_argument(
        "--group-color",
        action="append",
        default=argparse.SUPPRESS,
        metavar="GROUP=#RRGGBB",
        help="Explicit group color mapping. Repeat for multiple groups.",
    )
    parser.add_argument(
        "--label-mode",
        choices=LABEL_MODES,
        default=argparse.SUPPRESS,
        help="Overlay label mode.",
    )
    parser.add_argument(
        "--label-position",
        choices=LABEL_POSITIONS,
        default=argparse.SUPPRESS,
        help="Overlay label position.",
    )
    parser.add_argument(
        "--label-size",
        type=int,
        default=argparse.SUPPRESS,
        help="Overlay label font size.",
    )
    parser.add_argument(
        "--label-color",
        default=argparse.SUPPRESS,
        help="Overlay label CSS/Pillow color.",
    )
    parser.add_argument(
        "--label-opacity",
        type=float,
        default=argparse.SUPPRESS,
        help="Overlay label opacity from 0 to 1.",
    )
    parser.add_argument(
        "--label-margin",
        type=int,
        default=argparse.SUPPRESS,
        help="Overlay label margin in pixels.",
    )
    args = parser.parse_args()
    try:
        config_path = (
            resolve_project_path(args.config, project_root=PROJECT_ROOT)
            if args.config is not None
            else None
        )
        config = load_render_config(config_path)
    except KeyframeDataError as exc:
        parser.error(str(exc))

    input_path = resolve_project_path(
        setting(
            args,
            config,
            "input",
            PROJECT_ROOT / "examples" / "simple_keyframes.csv",
        ),
        project_root=PROJECT_ROOT,
    )
    table = load_keyframes(input_path)
    aspect = str(setting(args, config, "aspect", DEFAULT_ASPECT))
    canvas_size = resolve_canvas_size(aspect)
    timing_values = resolve_timing_values(args, config)
    try:
        timing = resolve_animation_timing(
            table,
            frames_per_transition=timing_values["frames_per_transition"],
            fps=timing_values["fps"],
            total_duration_seconds=timing_values["total_duration"],
            seconds_per_transition=timing_values["seconds_per_transition"],
        )
    except KeyframeDataError as exc:
        parser.error(str(exc))
    try:
        label_config = build_label_config(args, config)
        use_physics = optional_bool(
            setting(args, config, "physics", False),
            "physics",
        )
        interpolation = resolve_interpolation(args, config)
        color_options = resolve_color_options(
            args,
            config,
            project_root=PROJECT_ROOT,
        )
        export_formats = resolve_export_formats(args, config)
    except KeyframeDataError as exc:
        parser.error(str(exc))
    output_name = "physics_animation" if use_physics else "fixed_animation"
    output_dir = resolve_project_path(
        setting(
            args,
            config,
            "output_dir",
            PROJECT_ROOT / "output" / (
                "physics_frames" if use_physics else "fixed_frames"
            ),
        ),
        project_root=PROJECT_ROOT,
    )
    export_paths = resolve_export_paths(
        setting(args, config, "output", None),
        output_name=output_name,
        formats=export_formats,
        project_root=PROJECT_ROOT,
    )
    frame_paths = render_fixed_animation_frames(
        table,
        output_dir,
        frames_per_transition=timing.frames_per_transition,
        width=canvas_size.width,
        height=canvas_size.height,
        random_state=7,
        use_physics=use_physics,
        label_config=label_config,
        interpolation=interpolation,
        color_options=color_options,
    )
    relative_output_dir = display_path(output_dir, project_root=PROJECT_ROOT)
    print(f"Wrote {len(frame_paths)} frames to {relative_output_dir}")
    print(f"Canvas: {canvas_size.width}x{canvas_size.height} ({aspect})")
    print(f"Interpolation: {interpolation}")
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

    if "gif" in export_formats:
        gif_path = export_gif(
            frame_paths,
            export_paths["gif"],
            fps=timing.fps,
        )
        print(f"Wrote {display_path(gif_path, project_root=PROJECT_ROOT)}")

    if "mp4" in export_formats:
        mp4_path = export_mp4(
            frame_paths,
            export_paths["mp4"],
            fps=timing.fps,
        )
        print(f"Wrote {display_path(mp4_path, project_root=PROJECT_ROOT)}")

    if "svg" in export_formats:
        svg_path = export_svg(
            table,
            export_paths["svg"],
            frames_per_transition=timing.frames_per_transition,
            fps=timing.fps,
            duration_seconds=timing.duration_seconds,
            width=canvas_size.width,
            height=canvas_size.height,
            random_state=7,
            use_physics=use_physics,
            label_config=label_config,
            interpolation=interpolation,
            color_options=color_options,
        )
        print(f"Wrote {display_path(svg_path, project_root=PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
