"""Command-line interface for Kinematic Word Cloud."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .api import RenderOptions, render_animation
from .background import is_transparent_background
from .config import ASPECT_CHOICES, DEFAULT_ASPECT, DEFAULT_FPS
from .data import KeyframeDataError
from .effects import BLOOM_INTENSITY_MODES, BLOOM_SOURCES
from .labels import LABEL_MODES, LABEL_POSITIONS
from .layout import (
    ABSOLUTECHANGE_COLOR_BY,
    COLOR_BY_MODES,
    COLOR_PALETTES,
    SCALEDCHANGE_COLOR_BY,
)
from .render_config import (
    build_bloom_config,
    build_label_config,
    display_path,
    load_render_config,
    optional_bool,
    resolve_color_options,
    resolve_export_formats,
    resolve_interpolation,
    resolve_layout_mode,
    resolve_project_path,
    resolve_scene_positioning,
    resolve_scene_settle_steps,
    resolve_scene_starts,
    resolve_size_max_value,
    resolve_timing_values,
    setting,
)
from .scenes import LAYOUT_MODES, SCENE_LAYOUT_MODE, SCENE_POSITIONING_MODES
from .timeline import INTERPOLATION_MODES


CLI_EPILOG = """\
Scene image assets:
  In --layout-mode scene, CSV rows with type=image can animate static PNG,
  JPEG, or WebP assets. Use explicit id and asset columns, optional
  asset_scale for responsive sizing, layer=front|back for draw order, and x/y
  center coordinates unless the id inherits a previous scene position. Use
  --physics when image items should participate in spacing.
"""


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Kinematic Word Cloud CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config_path = _resolve_config_path(args.config)
        config = load_render_config(config_path)
    except KeyframeDataError as exc:
        parser.error(str(exc))

    base_dir = config_path.parent if config_path is not None else Path.cwd()
    input_value = setting(args, config, "input", None)
    if input_value is None:
        parser.error("Provide --input or set input = 'path/to/keyframes.csv' in TOML.")

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
            project_root=base_dir,
        )
        bloom_config = build_bloom_config(args, config)
        size_max_value = resolve_size_max_value(args, config)
        layout_mode = resolve_layout_mode(args, config)
        scene_positioning = resolve_scene_positioning(args, config)
        scene_settle_steps = resolve_scene_settle_steps(args, config)
        scene_starts = resolve_scene_starts(args, config)
        export_formats = resolve_export_formats(args, config)
        timing_values = resolve_timing_values(args, config)
    except KeyframeDataError as exc:
        parser.error(str(exc))

    background_color = str(setting(args, config, "background_color", "white"))
    if is_transparent_background(background_color) and "mp4" in export_formats:
        parser.error(
            "Transparent backgrounds cannot be preserved in standard MP4 export. "
            "Use --frames-only, --exports frames, or an opaque background."
        )
    if layout_mode == SCENE_LAYOUT_MODE and "svg" in export_formats:
        parser.error(
            "Scene layout mode does not support SVG export yet. "
            "Use --exports frames, gif, or mp4."
        )

    aspect = str(setting(args, config, "aspect", DEFAULT_ASPECT))
    output_name = (
        "scene_animation"
        if layout_mode == SCENE_LAYOUT_MODE
        else "physics_animation" if use_physics else "fixed_animation"
    )
    output_dir = resolve_project_path(
        setting(
            args,
            config,
            "output_dir",
            Path("output")
            / (
                "scene_frames"
                if layout_mode == SCENE_LAYOUT_MODE
                else "physics_frames" if use_physics else "fixed_frames"
            ),
        ),
        project_root=base_dir,
    )
    try:
        result = render_animation(
            RenderOptions(
                input_path=resolve_project_path(input_value, project_root=base_dir),
                output_dir=output_dir,
                output=setting(args, config, "output", None),
                exports=export_formats,
                aspect=aspect,
                background_color=background_color,
                frames_per_transition=timing_values["frames_per_transition"],
                fps=timing_values["fps"],
                total_duration=timing_values["total_duration"],
                seconds_per_transition=timing_values["seconds_per_transition"],
                use_physics=use_physics,
                label_config=label_config,
                interpolation=interpolation,
                color_options=color_options,
                bloom_config=bloom_config,
                size_max_value=size_max_value,
                random_state=7,
                output_name=output_name,
                base_dir=base_dir,
                layout_mode=layout_mode,
                scene_starts=scene_starts,
                scene_positioning=scene_positioning,
                scene_settle_steps=scene_settle_steps,
            )
        )
    except KeyframeDataError as exc:
        parser.error(str(exc))

    _print_summary(
        result=result,
        base_dir=base_dir,
        aspect=aspect,
        background_color=background_color,
        layout_mode=layout_mode,
        scene_positioning=scene_positioning,
        scene_settle_steps=scene_settle_steps,
        interpolation=interpolation,
        size_max_value=size_max_value,
        color_options=color_options,
        bloom_config=bloom_config,
        export_formats=export_formats,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""

    parser = argparse.ArgumentParser(
        description="Animate word clouds from tabular keyframe data.",
        epilog=CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
        "--layout-mode",
        choices=LAYOUT_MODES,
        default=argparse.SUPPRESS,
        help=(
            "Layout strategy: global peak layout or per-scene layouts. "
            "Scene CSVs may include type=image asset rows."
        ),
    )
    parser.add_argument(
        "--scene-start",
        action="append",
        default=argparse.SUPPRESS,
        metavar="SCENE=FRAME",
        help="Scene start label for --layout-mode scene. Repeat for each scene.",
    )
    parser.add_argument(
        "--scene-positioning",
        choices=SCENE_POSITIONING_MODES,
        default=argparse.SUPPRESS,
        help=(
            "Scene positioning strategy. settled-center seeds items around the "
            "canvas, pulls them toward the center with hidden physics warmup, "
            "then starts rendering from the settled state."
        ),
    )
    parser.add_argument(
        "--scene-settle-steps",
        type=int,
        default=argparse.SUPPRESS,
        help="Hidden physics warmup steps for --scene-positioning settled-center.",
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
    return parser


def _print_summary(
    *,
    result,
    base_dir: Path,
    aspect: str,
    background_color: str,
    layout_mode: str,
    scene_positioning: str,
    scene_settle_steps: int,
    interpolation: str,
    size_max_value: float | None,
    color_options,
    bloom_config,
    export_formats: set[str],
) -> None:
    relative_output_dir = display_path(result.output_dir, project_root=base_dir)
    print(f"Wrote {len(result.frame_paths)} frames to {relative_output_dir}")
    print(f"Canvas: {result.canvas_size.width}x{result.canvas_size.height} ({aspect})")
    print(f"Background: {background_color}")
    print(f"Layout mode: {layout_mode}")
    if layout_mode == SCENE_LAYOUT_MODE:
        print(f"Scene positioning: {scene_positioning}")
        if scene_positioning != "wordcloud":
            print(f"Scene settle steps: {scene_settle_steps}")
    if result.scene_render_info:
        print(
            "Scenes: "
            + ", ".join(
                f"{scene.name} ({scene.frame_count} frames)"
                for scene in result.scene_render_info
            )
        )
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
        f", target {result.timing.target_fps:.3f} fps"
        if abs(result.timing.fps - result.timing.target_fps) > 0.001
        else ""
    )
    print(
        "Timing: "
        f"{result.timing.duration_seconds:.3f}s total, "
        f"{result.timing.seconds_per_transition:.3f}s/transition, "
        f"{result.timing.frame_count} frames, "
        f"{result.timing.frames_per_transition} frames/transition, "
        f"{result.timing.fps:.3f} fps"
        f"{target_fps}"
    )
    for export_format in ("gif", "mp4", "svg"):
        if export_format in result.export_paths:
            print(
                "Wrote "
                f"{display_path(result.export_paths[export_format], project_root=base_dir)}"
            )


def _resolve_config_path(path: Path | None) -> Path | None:
    if path is None:
        return None
    return path if path.is_absolute() else Path.cwd() / path


if __name__ == "__main__":
    main()
