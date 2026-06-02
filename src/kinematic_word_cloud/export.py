"""Export word-cloud animations to GIF, MP4, and SVG."""

from __future__ import annotations

from html import escape
from pathlib import Path
import subprocess

from PIL import Image

from .change_color import (
    color_for_absolute_change,
    color_for_scaled_change,
    max_absolute_change,
)
from .config import DEFAULT_CANVAS_SIZE
from .data import KeyframeTable
from .labels import LabelConfig, sample_labels, svg_label_position
from .layout import (
    ABSOLUTECHANGE_COLOR_BY,
    ColorOptions,
    SCALEDCHANGE_COLOR_BY,
    build_peak_layout,
)
from .physics import PhysicsConfig
from .render import (
    _build_anchor_layout,
    _build_physics_simulator,
    _layout_centers,
    _measure_peak_sizes,
)
from .timeline import DEFAULT_INTERPOLATION, iter_timeline_frames


class ExportError(RuntimeError):
    """Raised when animation export fails."""


SvgWordSample = dict[str, float | str]
SvgFrameSample = dict[str, SvgWordSample]


def export_gif(
    frame_paths: list[Path],
    output_path: str | Path,
    *,
    fps: float = 12,
    loop: int = 0,
) -> Path:
    """Export a PNG frame sequence to an animated GIF."""

    frames = _validate_frame_paths(frame_paths)
    if fps <= 0:
        raise ExportError("fps must be greater than zero.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    duration_ms = int(round(1000 / fps))
    images = [Image.open(path).convert("P", palette=Image.Palette.ADAPTIVE) for path in frames]
    first, rest = images[0], images[1:]
    try:
        first.save(
            output,
            save_all=True,
            append_images=rest,
            duration=duration_ms,
            loop=loop,
            optimize=False,
        )
    finally:
        for image in images:
            image.close()

    return output


def export_mp4(
    frame_paths: list[Path],
    output_path: str | Path,
    *,
    fps: float = 24,
    ffmpeg_binary: str = "ffmpeg",
) -> Path:
    """Export a PNG frame sequence to MP4 using ffmpeg."""

    frames = _validate_frame_paths(frame_paths)
    if fps <= 0:
        raise ExportError("fps must be greater than zero.")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    input_pattern = _frame_input_pattern(frames)

    command = [
        ffmpeg_binary,
        "-y",
        "-framerate",
        _fmt_rate(fps),
        "-i",
        input_pattern,
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise ExportError(
            f"ffmpeg binary not found: {ffmpeg_binary!r}. Install ffmpeg or pass "
            "a valid ffmpeg path."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise ExportError(f"ffmpeg failed: {exc.stderr.strip()}") from exc

    return output


def export_svg(
    table: KeyframeTable,
    output_path: str | Path,
    *,
    frames_per_transition: int = 12,
    fps: float = 12,
    duration_seconds: float | None = None,
    width: int = DEFAULT_CANVAS_SIZE.width,
    height: int = DEFAULT_CANVAS_SIZE.height,
    background_color: str = "white",
    random_state: int = 42,
    colormap: str = "viridis",
    min_font_size: int = 4,
    use_physics: bool = False,
    physics_config: PhysicsConfig | None = None,
    label_config: LabelConfig | None = None,
    interpolation: str = DEFAULT_INTERPOLATION,
    color_options: ColorOptions | None = None,
    repeat_count: str = "indefinite",
) -> Path:
    """Export a sampled animated SVG from the keyframe table."""

    if fps <= 0:
        raise ExportError("fps must be greater than zero.")

    layout = build_peak_layout(
        table,
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
        color_options=color_options,
    )
    samples = _sample_svg_frames(
        table,
        layout=layout,
        frames_per_transition=frames_per_transition,
        min_font_size=min_font_size,
        use_physics=use_physics,
        physics_config=physics_config,
        interpolation=interpolation,
        color_options=color_options,
    )
    duration = (
        float(duration_seconds)
        if duration_seconds is not None
        else len(samples) / float(fps)
    )
    if duration <= 0:
        raise ExportError("duration_seconds must be greater than zero.")
    key_times = _svg_key_times(len(samples))
    label_samples = sample_labels(
        table,
        frames_per_transition=frames_per_transition,
        config=label_config,
        interpolation=interpolation,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        _build_svg_document(
            layout=layout,
            samples=samples,
            width=width,
            height=height,
            background_color=background_color,
            duration=duration,
            key_times=key_times,
            repeat_count=repeat_count,
            label_config=label_config,
            label_samples=label_samples,
        ),
        encoding="utf-8",
    )
    return output


def _validate_frame_paths(frame_paths: list[Path]) -> list[Path]:
    frames = [Path(path) for path in frame_paths]
    if not frames:
        raise ExportError("At least one frame is required for export.")

    missing = [path for path in frames if not path.exists()]
    if missing:
        raise ExportError(f"Frame does not exist: {missing[0]}")

    return sorted(frames)


def _frame_input_pattern(frame_paths: list[Path]) -> str:
    first = frame_paths[0]
    expected_names = [f"frame_{index:04d}.png" for index in range(len(frame_paths))]
    if [path.name for path in frame_paths] != expected_names:
        raise ExportError(
            "MP4 export expects frames named frame_0000.png, frame_0001.png, ..."
        )

    extra_frame = first.parent / f"frame_{len(frame_paths):04d}.png"
    if extra_frame.exists():
        raise ExportError(
            f"Unexpected extra frame exists after the export sequence: {extra_frame}"
        )

    return str(first.parent / "frame_%04d.png")


def _sample_svg_frames(
    table: KeyframeTable,
    *,
    layout,
    frames_per_transition: int,
    min_font_size: int,
    use_physics: bool,
    physics_config: PhysicsConfig | None,
    interpolation: str,
    color_options: ColorOptions | None,
) -> list[SvgFrameSample]:
    font_path = getattr(layout.wordcloud, "font_path")
    peak_sizes = _measure_peak_sizes(layout, font_path=font_path)
    fixed_centers = _layout_centers(layout, peak_sizes)
    simulator = None
    if use_physics:
        anchor_layout = _build_anchor_layout(
            table,
            width=layout.width,
            height=layout.height,
            background_color=getattr(layout.wordcloud, "background_color", "white"),
            random_state=getattr(layout.wordcloud, "random_state", 42),
            colormap=getattr(layout.wordcloud, "colormap", "viridis"),
            color_options=color_options,
        )
        simulator = _build_physics_simulator(
            layout,
            anchor_layout=anchor_layout,
            canvas_size=(layout.width, layout.height),
            config=physics_config,
        )

    peak_values = table.peak_values()
    color_by_absolutechange = (
        color_options is not None
        and color_options.color_by == ABSOLUTECHANGE_COLOR_BY
    )
    color_by_scaledchange = (
        color_options is not None
        and color_options.color_by == SCALEDCHANGE_COLOR_BY
    )
    uses_transition_colors = color_by_absolutechange or color_by_scaledchange
    scaledchange_max_absolute_change = (
        max_absolute_change(table.frame_values(frame) for frame in table.frames)
        if color_by_scaledchange
        else 0.0
    )
    samples: list[SvgFrameSample] = []
    for frame in iter_timeline_frames(
        table,
        frames_per_transition=frames_per_transition,
        interpolation=interpolation,
    ):
        centers = (
            simulator.step(frame.values, peak_values)
            if simulator is not None
            else fixed_centers
        )
        change_start_values = (
            table.frame_values(frame.start_keyframe)
            if uses_transition_colors
            else {}
        )
        change_end_values = (
            table.frame_values(frame.end_keyframe)
            if uses_transition_colors
            else {}
        )
        frame_sample: SvgFrameSample = {}
        for word_layout in layout.words:
            peak_value = peak_values.get(word_layout.word, 0.0)
            current_value = float(frame.values.get(word_layout.word, 0.0))
            scale = 0.0 if peak_value <= 0 else current_value / peak_value
            font_size = (
                min_font_size
                if scale <= 0
                else max(float(min_font_size), word_layout.font_size * scale)
            )
            opacity = 0.0 if scale <= 0 else 1.0
            center_x, center_y = centers[word_layout.word]
            word_color = word_layout.color
            if (
                color_options is not None
                and color_options.color_by == ABSOLUTECHANGE_COLOR_BY
            ):
                word_color = color_for_absolute_change(
                    word_layout.word,
                    change_start_values,
                    change_end_values,
                    growth_color=color_options.absolutechange_growth_color,
                    decline_color=color_options.absolutechange_decline_color,
                    no_change_color=color_options.absolutechange_no_change_color,
                )
            elif (
                color_options is not None
                and color_options.color_by == SCALEDCHANGE_COLOR_BY
            ):
                word_color = color_for_scaled_change(
                    word_layout.word,
                    change_start_values,
                    change_end_values,
                    max_absolute_change=scaledchange_max_absolute_change,
                    colors=color_options.scaledchange_colors,
                )
            frame_sample[word_layout.word] = {
                "x": center_x,
                "y": center_y,
                "font_size": font_size,
                "opacity": opacity,
                "color": word_color,
            }
        samples.append(frame_sample)

    return samples


def _build_svg_document(
    layout,
    *,
    samples: list[SvgFrameSample],
    width: int,
    height: int,
    background_color: str,
    duration: float,
    key_times: str,
    repeat_count: str,
    label_config: LabelConfig | None,
    label_samples: list[str | None],
) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        ),
        f'  <rect width="100%" height="100%" fill="{escape(background_color)}" />',
        '  <g font-family="monospace" text-anchor="middle" dominant-baseline="central">',
    ]

    for word_layout in layout.words:
        word = word_layout.word
        first = samples[0][word]
        rotate = _svg_rotation(word_layout.orientation)
        transform = f' transform="{rotate}"' if rotate else ""
        lines.append(
            f'    <g transform="translate({_fmt(first["x"])} {_fmt(first["y"])})">'
        )
        lines.extend(
            [
                _animate_transform_line(
                    _translate_values(samples, word),
                    duration,
                    key_times,
                    repeat_count,
                ),
                (
                    f'      <text x="0" y="0" '
                    f'font-size="{_fmt(first["font_size"])}" '
                    f'fill="{escape(str(first["color"]))}" '
                    f'opacity="{_fmt(first["opacity"])}"{transform}>'
                ),
                _animate_line(
                    "font-size",
                    _sample_values(samples, word, "font_size"),
                    duration,
                    key_times,
                    repeat_count,
                ),
                _animate_line(
                    "opacity",
                    _sample_values(samples, word, "opacity"),
                    duration,
                    key_times,
                    repeat_count,
                ),
                _animate_color_line(
                    "fill",
                    _sample_color_values(samples, word),
                    duration,
                    key_times,
                    repeat_count,
                    calc_mode="discrete",
                ),
                f"        {escape(word)}",
                "      </text>",
                "    </g>",
            ]
        )

    lines.append("  </g>")
    lines.extend(
        _build_svg_label_lines(
            label_config=label_config,
            label_samples=label_samples,
            width=width,
            height=height,
            duration=duration,
            key_times=key_times,
            repeat_count=repeat_count,
        )
    )
    lines.extend(["</svg>", ""])
    return "\n".join(lines)


def _animate_line(
    attribute: str,
    values: list[float],
    duration: float,
    key_times: str,
    repeat_count: str,
    *,
    calc_mode: str | None = None,
) -> str:
    values_text = ";".join(_fmt(value) for value in values)
    calc_mode_text = f' calcMode="{escape(calc_mode)}"' if calc_mode else ""
    return (
        f'      <animate attributeName="{attribute}" values="{values_text}" '
        f'keyTimes="{key_times}" dur="{_fmt(duration)}s" '
        f'repeatCount="{escape(repeat_count)}"{calc_mode_text} />'
    )


def _animate_color_line(
    attribute: str,
    values: list[str],
    duration: float,
    key_times: str,
    repeat_count: str,
    *,
    calc_mode: str | None = None,
) -> str:
    values_text = ";".join(escape(value) for value in values)
    calc_mode_text = f' calcMode="{escape(calc_mode)}"' if calc_mode else ""
    return (
        f'      <animate attributeName="{attribute}" values="{values_text}" '
        f'keyTimes="{key_times}" dur="{_fmt(duration)}s" '
        f'repeatCount="{escape(repeat_count)}"{calc_mode_text} />'
    )


def _build_svg_label_lines(
    *,
    label_config: LabelConfig | None,
    label_samples: list[str | None],
    width: int,
    height: int,
    duration: float,
    key_times: str,
    repeat_count: str,
) -> list[str]:
    if label_config is None or label_config.mode == "none":
        return []

    unique_labels = list(dict.fromkeys(label for label in label_samples if label))
    if not unique_labels:
        return []

    x, y, anchor, baseline = svg_label_position(
        width=width,
        height=height,
        config=label_config,
    )
    lines = [
        (
            f'  <g font-family="monospace" text-anchor="{anchor}" '
            f'dominant-baseline="{baseline}">'
        )
    ]
    for label in unique_labels:
        opacity_values = [
            label_config.opacity if sample == label else 0.0
            for sample in label_samples
        ]
        lines.extend(
            [
                (
                    f'    <text x="{_fmt(x)}" y="{_fmt(y)}" '
                    f'font-size="{_fmt(label_config.font_size)}" '
                    f'fill="{escape(label_config.color)}" '
                    f'opacity="{_fmt(opacity_values[0])}">'
                ),
                _animate_line(
                    "opacity",
                    opacity_values,
                    duration,
                    key_times,
                    repeat_count,
                    calc_mode="discrete",
                ),
                f"      {escape(label)}",
                "    </text>",
            ]
        )

    lines.append("  </g>")
    return lines


def _animate_transform_line(
    values: list[tuple[float, float]],
    duration: float,
    key_times: str,
    repeat_count: str,
) -> str:
    values_text = ";".join(f"{_fmt(x)} {_fmt(y)}" for x, y in values)
    return (
        f'      <animateTransform attributeName="transform" type="translate" '
        f'values="{values_text}" keyTimes="{key_times}" dur="{_fmt(duration)}s" '
        f'repeatCount="{escape(repeat_count)}" />'
    )


def _translate_values(
    samples: list[SvgFrameSample],
    word: str,
) -> list[tuple[float, float]]:
    return [
        (float(sample[word]["x"]), float(sample[word]["y"]))
        for sample in samples
    ]


def _sample_values(
    samples: list[SvgFrameSample],
    word: str,
    field: str,
) -> list[float]:
    return [float(sample[word][field]) for sample in samples]


def _sample_color_values(
    samples: list[SvgFrameSample],
    word: str,
) -> list[str]:
    return [str(sample[word]["color"]) for sample in samples]


def _svg_key_times(sample_count: int) -> str:
    if sample_count <= 1:
        return "0"
    return ";".join(_fmt(index / (sample_count - 1)) for index in range(sample_count))


def _svg_rotation(orientation) -> str | None:
    if orientation is None:
        return None
    return "rotate(-90)"


def _fmt(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


def _fmt_rate(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")
