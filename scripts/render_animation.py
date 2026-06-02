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

from kinematic_word_cloud.background import is_transparent_background
from kinematic_word_cloud.config import (
    ASPECT_CHOICES,
    DEFAULT_ASPECT,
    DEFAULT_FPS,
    resolve_animation_timing,
    resolve_canvas_size,
)
from kinematic_word_cloud.data import KeyframeDataError, load_keyframes
from kinematic_word_cloud.effects import BLOOM_INTENSITY_MODES, BLOOM_SOURCES
from kinematic_word_cloud.export import export_gif, export_mp4, export_svg
from kinematic_word_cloud.labels import LABEL_MODES, LABEL_POSITIONS
from kinematic_word_cloud.layout import (
    ABSOLUTECHANGE_COLOR_BY,
    COLOR_BY_MODES,
    COLOR_PALETTES,
    SCALEDCHANGE_COLOR_BY,
)
from kinematic_word_cloud.render_config import (
    build_bloom_config,
    build_label_config,
    display_path,
    load_render_config,
    optional_bool,
    resolve_color_options,
    resolve_export_formats,
    resolve_export_paths,
    resolve_interpolation,
    resolve_project_path,
    resolve_size_max_value,
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
        "--background-color",
        default=argparse.SUPPRESS,
        help="Canvas background color for PNG, GIF, MP4, and SVG outputs.",
    )
    bloom_group = parser.add_mutually_exclusive_group()
    bloom_group.add_argument(
        "--bloom",
        dest="bloom",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Enable per-word raster bloom for PNG frames, GIF, and MP4.",
    )
    bloom_group.add_argument(
        "--no-bloom",
        dest="bloom",
        action="store_false",
        default=argparse.SUPPRESS,
        help="Disable raster bloom from a config file.",
    )
    parser.add_argument(
        "--bloom-radius-scale",
        type=float,
        default=argparse.SUPPRESS,
        help="Bloom blur radius as a fraction of current word font size.",
    )
    parser.add_argument(
        "--bloom-min-radius",
        type=float,
        default=argparse.SUPPRESS,
        help="Smallest bloom blur radius in pixels.",
    )
    parser.add_argument(
        "--bloom-max-radius",
        type=float,
        default=argparse.SUPPRESS,
        help="Largest bloom blur radius in pixels.",
    )
    parser.add_argument(
        "--bloom-strength",
        type=float,
        default=argparse.SUPPRESS,
        help="Bloom opacity multiplier.",
    )
    parser.add_argument(
        "--bloom-color",
        default=argparse.SUPPRESS,
        help=(
            "Optional glow color for bloom, such as word, white, or #FFFFFF. "
            "Defaults to each word's own color."
        ),
    )
    parser.add_argument(
        "--bloom-source",
        choices=BLOOM_SOURCES,
        default=argparse.SUPPRESS,
        help="Bloom source mask. Edge keeps glow tied to letter outlines.",
    )
    parser.add_argument(
        "--bloom-edge-width",
        type=int,
        default=argparse.SUPPRESS,
        help="Edge-mask width in pixels when --bloom-source edge.",
    )
    parser.add_argument(
        "--bloom-intensity-power",
        type=float,
        default=argparse.SUPPRESS,
        help=(
            "How strongly bloom intensity follows current word size. "
            "Use 0 for constant strength."
        ),
    )
    parser.add_argument(
        "--bloom-intensity-mode",
        choices=BLOOM_INTENSITY_MODES,
        default=argparse.SUPPRESS,
        help=(
            "How bloom strength scales: absolute current size, relative to "
            "each word's peak, or constant."
        ),
    )
    parser.add_argument(
        "--bloom-layers",
        type=int,
        default=argparse.SUPPRESS,
        help="Number of increasingly soft bloom layers per word.",
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
            "Animation export formats: frames, gif, mp4, svg. Accepts space- or "
            "comma-separated values."
        ),
    )
    parser.add_argument(
        "--frames-only",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Write the PNG frame sequence and skip GIF, MP4, and SVG export.",
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
        "--size-max-value",
        type=float,
        default=argparse.SUPPRESS,
        help=(
            "Input value that maps to maximum word size. Useful when rendering "
            "segments whose local peaks should stay below a later global max."
        ),
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
        help=(
            "How to color words. Change modes override configured and "
            "spreadsheet colors per keyframe transition."
        ),
    )
    parser.add_argument(
        "--default-color",
        default=argparse.SUPPRESS,
        help="Fallback hex color used when --color-by single.",
    )
    parser.add_argument(
        "--absolutechange-growth-color",
        default=argparse.SUPPRESS,
        help="Hex color for words growing in --color-by absolutechange mode.",
    )
    parser.add_argument(
        "--absolutechange-decline-color",
        default=argparse.SUPPRESS,
        help="Hex color for words shrinking in --color-by absolutechange mode.",
    )
    parser.add_argument(
        "--absolutechange-no-change-color",
        default=argparse.SUPPRESS,
        help="Hex color for unchanged words in --color-by absolutechange mode.",
    )
    parser.add_argument(
        "--scaledchange-colors",
        nargs="+",
        default=argparse.SUPPRESS,
        metavar="COLOR",
        help=(
            "Ordered color stops for --color-by scaledchange. Accepts "
            "space-separated or comma-separated hex colors."
        ),
    )
    parser.add_argument(
        "--group-color",
        action="append",
        default=argparse.SUPPRESS,
        metavar="GROUP=#RRGGBB[AA]",
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
    background_color = str(setting(args, config, "background_color", "white"))
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
        bloom_config = build_bloom_config(args, config)
        size_max_value = resolve_size_max_value(args, config)
        export_formats = resolve_export_formats(args, config)
    except KeyframeDataError as exc:
        parser.error(str(exc))
    if is_transparent_background(background_color) and "mp4" in export_formats:
        parser.error(
            "Transparent backgrounds cannot be preserved in standard MP4 export. "
            "Use --frames-only, --exports frames, or an opaque background."
        )
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
        background_color=background_color,
        random_state=7,
        use_physics=use_physics,
        label_config=label_config,
        interpolation=interpolation,
        color_options=color_options,
        bloom_config=bloom_config,
        size_max_value=size_max_value,
    )
    relative_output_dir = display_path(output_dir, project_root=PROJECT_ROOT)
    print(f"Wrote {len(frame_paths)} frames to {relative_output_dir}")
    print(f"Canvas: {canvas_size.width}x{canvas_size.height} ({aspect})")
    print(f"Background: {background_color}")
    print(f"Interpolation: {interpolation}")
    if size_max_value is not None:
        print(f"Size max value: {size_max_value:g}")
    print(f"Color by: {color_options.color_by}")
    if color_options.color_by == ABSOLUTECHANGE_COLOR_BY:
        print(
            "Absolutechange colors: "
            f"growth={color_options.absolutechange_growth_color}, "
            f"decline={color_options.absolutechange_decline_color}, "
            f"no_change={color_options.absolutechange_no_change_color}"
        )
    if color_options.color_by == SCALEDCHANGE_COLOR_BY:
        print(
            "Scaledchange colors: "
            f"{', '.join(color_options.scaledchange_colors)} "
            "(global signed delta scale)"
        )
    if bloom_config is not None:
        print(
            "Bloom: "
            f"radius_scale={bloom_config.radius_scale:g}, "
            f"radius={bloom_config.min_radius:g}-{bloom_config.max_radius:g}px, "
            f"strength={bloom_config.strength:g}, "
            f"color={bloom_config.color or 'word'}, "
            f"source={bloom_config.source}, "
            f"edge_width={bloom_config.edge_width}, "
            f"intensity_mode={bloom_config.intensity_mode}, "
            f"intensity_power={bloom_config.intensity_power:g}, "
            f"layers={bloom_config.layers} "
            "(raster frames, GIF, and MP4)"
        )
        if "svg" in export_formats:
            print("Bloom is not applied to SVG export yet.")
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
            background_color=background_color,
            random_state=7,
            use_physics=use_physics,
            label_config=label_config,
            interpolation=interpolation,
            color_options=color_options,
            size_max_value=size_max_value,
        )
        print(f"Wrote {display_path(svg_path, project_root=PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
