"""Public rendering API for Kinematic Word Cloud."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .background import is_transparent_background
from .config import (
    DEFAULT_ASPECT,
    AnimationTiming,
    CanvasSize,
    resolve_animation_timing,
    resolve_canvas_size,
)
from .data import KeyframeDataError, KeyframeTable, load_keyframes
from .effects import BloomConfig
from .export import export_gif, export_mp4, export_svg
from .labels import LabelConfig
from .layout import ColorOptions
from .render import render_fixed_animation_frames
from .render_config import EXPORT_FORMATS, resolve_export_paths
from .scenes import (
    DEFAULT_LAYOUT_MODE,
    SCENE_LAYOUT_MODE,
    LAYOUT_MODES,
    SceneKeyframeData,
    SceneRenderInfo,
    load_scene_keyframes,
    render_scene_animation_frames,
    resolve_scene_animation_timing,
)
from .timeline import DEFAULT_INTERPOLATION


@dataclass(frozen=True)
class RenderOptions:
    """Options for rendering a word-cloud animation from a CSV keyframe table."""

    input_path: str | Path
    output_dir: str | Path | None = None
    output: str | Path | None = None
    exports: Iterable[str] = ()
    aspect: str = DEFAULT_ASPECT
    background_color: str = "white"
    frames_per_transition: int | None = None
    fps: float | None = None
    total_duration: float | None = None
    seconds_per_transition: float | None = None
    use_physics: bool = False
    label_config: LabelConfig | None = None
    interpolation: str = DEFAULT_INTERPOLATION
    color_options: ColorOptions | None = None
    bloom_config: BloomConfig | None = None
    size_max_value: float | None = None
    random_state: int = 7
    min_font_size: int = 4
    output_name: str | None = None
    base_dir: str | Path | None = None
    ffmpeg_binary: str = "ffmpeg"
    layout_mode: str = DEFAULT_LAYOUT_MODE
    scene_starts: Mapping[str, str] | None = None


@dataclass(frozen=True)
class RenderResult:
    """Paths and resolved settings from a render run."""

    input_path: Path
    output_dir: Path
    frame_paths: list[Path]
    export_paths: dict[str, Path]
    timing: AnimationTiming
    canvas_size: CanvasSize
    table: KeyframeTable
    layout_mode: str
    scene_data: SceneKeyframeData | None = None
    scene_render_info: tuple[SceneRenderInfo, ...] = ()


def render_animation(options: RenderOptions) -> RenderResult:
    """Render frames and optional animation exports from a keyframe CSV."""

    base_dir = _resolve_base_dir(options.base_dir)
    input_path = _resolve_path(options.input_path, base_dir=base_dir)
    layout_mode = _normalize_layout_mode(options.layout_mode)
    canvas_size = resolve_canvas_size(options.aspect)
    export_formats = _normalize_export_formats(options.exports)
    if is_transparent_background(options.background_color) and "mp4" in export_formats:
        raise KeyframeDataError(
            "Transparent backgrounds cannot be preserved in standard MP4 export. "
            "Use frames-only output, exports=('frames',), or an opaque background."
        )
    if layout_mode == SCENE_LAYOUT_MODE and "svg" in export_formats:
        raise KeyframeDataError(
            "Scene layout mode does not support SVG export yet. "
            "Use frames, gif, or mp4."
        )

    output_name = options.output_name or _default_output_name(
        layout_mode,
        use_physics=options.use_physics,
    )
    output_dir = _resolve_path(
        options.output_dir or Path("output") / _default_output_dir_name(
            layout_mode,
            use_physics=options.use_physics,
        ),
        base_dir=base_dir,
    )
    resolved_export_paths = resolve_export_paths(
        options.output,
        output_name=output_name,
        formats=export_formats,
        project_root=base_dir,
    )
    scene_data: SceneKeyframeData | None = None
    scene_render_info: tuple[SceneRenderInfo, ...] = ()
    if layout_mode == SCENE_LAYOUT_MODE:
        scene_data = load_scene_keyframes(
            input_path,
            scene_starts=options.scene_starts or {},
        )
        table = scene_data.timeline_table()
        timing = resolve_scene_animation_timing(
            scene_data,
            frames_per_transition=options.frames_per_transition,
            fps=options.fps,
            total_duration_seconds=options.total_duration,
            seconds_per_transition=options.seconds_per_transition,
        )
        frame_paths, scene_render_info = render_scene_animation_frames(
            scene_data,
            output_dir,
            frames_per_transition=timing.frames_per_transition,
            width=canvas_size.width,
            height=canvas_size.height,
            background_color=options.background_color,
            random_state=options.random_state,
            min_font_size=options.min_font_size,
            use_physics=options.use_physics,
            label_config=options.label_config,
            interpolation=options.interpolation,
            color_options=options.color_options,
            bloom_config=options.bloom_config,
            size_max_value=options.size_max_value,
        )
    else:
        table = load_keyframes(input_path)
        timing = resolve_animation_timing(
            table,
            frames_per_transition=options.frames_per_transition,
            fps=options.fps,
            total_duration_seconds=options.total_duration,
            seconds_per_transition=options.seconds_per_transition,
        )
        frame_paths = render_fixed_animation_frames(
            table,
            output_dir,
            frames_per_transition=timing.frames_per_transition,
            width=canvas_size.width,
            height=canvas_size.height,
            background_color=options.background_color,
            random_state=options.random_state,
            min_font_size=options.min_font_size,
            use_physics=options.use_physics,
            label_config=options.label_config,
            interpolation=options.interpolation,
            color_options=options.color_options,
            bloom_config=options.bloom_config,
            size_max_value=options.size_max_value,
        )

    written_exports: dict[str, Path] = {}
    if "gif" in export_formats:
        written_exports["gif"] = export_gif(
            frame_paths,
            resolved_export_paths["gif"],
            fps=timing.fps,
        )
    if "mp4" in export_formats:
        written_exports["mp4"] = export_mp4(
            frame_paths,
            resolved_export_paths["mp4"],
            fps=timing.fps,
            ffmpeg_binary=options.ffmpeg_binary,
        )
    if "svg" in export_formats:
        written_exports["svg"] = export_svg(
            table,
            resolved_export_paths["svg"],
            frames_per_transition=timing.frames_per_transition,
            fps=timing.fps,
            duration_seconds=timing.duration_seconds,
            width=canvas_size.width,
            height=canvas_size.height,
            background_color=options.background_color,
            random_state=options.random_state,
            use_physics=options.use_physics,
            label_config=options.label_config,
            interpolation=options.interpolation,
            color_options=options.color_options,
            size_max_value=options.size_max_value,
        )

    return RenderResult(
        input_path=input_path,
        output_dir=output_dir,
        frame_paths=frame_paths,
        export_paths=written_exports,
        timing=timing,
        canvas_size=canvas_size,
        table=table,
        layout_mode=layout_mode,
        scene_data=scene_data,
        scene_render_info=scene_render_info,
    )


def render_from_csv(input_path: str | Path, **kwargs: Any) -> RenderResult:
    """Convenience wrapper for rendering directly from a CSV path."""

    return render_animation(RenderOptions(input_path=input_path, **kwargs))


def _resolve_base_dir(base_dir: str | Path | None) -> Path:
    return Path.cwd() if base_dir is None else Path(base_dir).resolve()


def _resolve_path(path: str | Path, *, base_dir: Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else base_dir / value


def _normalize_export_formats(exports: Iterable[str]) -> set[str]:
    formats: set[str] = set()
    raw_values = [exports] if isinstance(exports, str) else exports
    for raw_value in raw_values:
        for part in str(raw_value).replace(",", " ").split():
            export_format = part.strip().lower()
            if not export_format:
                continue
            if export_format not in EXPORT_FORMATS:
                raise KeyframeDataError(
                    "exports must contain only: " + ", ".join(EXPORT_FORMATS)
                )
            if export_format != "frames":
                formats.add(export_format)
    return formats


def _normalize_layout_mode(layout_mode: str) -> str:
    normalized = str(layout_mode).strip().lower()
    if normalized not in LAYOUT_MODES:
        raise KeyframeDataError(
            "layout_mode must be one of: " + ", ".join(LAYOUT_MODES)
        )
    return normalized


def _default_output_name(layout_mode: str, *, use_physics: bool) -> str:
    if layout_mode == SCENE_LAYOUT_MODE:
        return "scene_animation"
    return "physics_animation" if use_physics else "fixed_animation"


def _default_output_dir_name(layout_mode: str, *, use_physics: bool) -> str:
    if layout_mode == SCENE_LAYOUT_MODE:
        return "scene_frames"
    return "physics_frames" if use_physics else "fixed_frames"
