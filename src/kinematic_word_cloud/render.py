"""Frame rendering utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont

from .config import DEFAULT_CANVAS_SIZE
from .data import KeyframeTable
from .labels import LabelConfig, label_for_frame, render_label_overlay
from .layout import CloudLayout, build_layout_from_frequencies, build_peak_layout
from .physics import PhysicsConfig, PhysicsSimulator, WordBodySpec
from .timeline import DEFAULT_INTERPOLATION, iter_timeline_frames


def render_peak_cloud(
    table: KeyframeTable,
    output_path: str | Path,
    *,
    width: int = DEFAULT_CANVAS_SIZE.width,
    height: int = DEFAULT_CANVAS_SIZE.height,
    background_color: str = "white",
    random_state: int = 42,
    colormap: str = "viridis",
) -> CloudLayout:
    """Render the peak-value starting cloud to an image file."""

    layout = build_peak_layout(
        table,
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    layout.wordcloud.to_file(str(output))
    return layout


def render_fixed_frame(
    table: KeyframeTable,
    layout: CloudLayout,
    values: Mapping[str, float],
    output_path: str | Path,
    *,
    background_color: str | None = None,
    min_font_size: int = 4,
    centers: Mapping[str, tuple[float, float]] | None = None,
    label_text: str | None = None,
    label_config: LabelConfig | None = None,
) -> Image.Image:
    """Render one fixed-position frame with size scaled by current values."""

    wordcloud = layout.wordcloud
    background = (
        background_color
        if background_color is not None
        else getattr(wordcloud, "background_color", "white")
    )
    image = Image.new(
        getattr(wordcloud, "mode", "RGB"),
        (layout.width, layout.height),
        background,
    )
    font_path = getattr(wordcloud, "font_path")
    peak_values = table.peak_values()
    peak_sizes = _measure_peak_sizes(layout, font_path=font_path)
    layout_centers = _layout_centers(layout, peak_sizes)

    for word_layout in layout.words:
        current_value = float(values.get(word_layout.word, 0.0))
        peak_value = peak_values.get(word_layout.word, 0.0)
        if current_value <= 0 or peak_value <= 0:
            continue

        scale = current_value / peak_value
        font_size = max(min_font_size, int(round(word_layout.font_size * scale)))
        current_image = _render_word_image(
            word_layout.word,
            font_path=font_path,
            font_size=font_size,
            orientation=word_layout.orientation,
            color=word_layout.color,
        )

        center_x, center_y = (
            centers.get(word_layout.word, layout_centers[word_layout.word])
            if centers is not None
            else layout_centers[word_layout.word]
        )
        paste_x = int(round(center_x - current_image.width / 2))
        paste_y = int(round(center_y - current_image.height / 2))
        image.paste(current_image, (paste_x, paste_y), current_image)

    render_label_overlay(
        image,
        label_text,
        config=label_config,
        font_path=font_path,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return image


def render_fixed_animation_frames(
    table: KeyframeTable,
    output_dir: str | Path,
    *,
    frames_per_transition: int = 12,
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
) -> list[Path]:
    """Render PNG frames for the whole keyframe timeline."""

    layout = build_peak_layout(
        table,
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
    )
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _clear_animation_frames(output)

    frame_paths: list[Path] = []
    anchor_layout = (
        _build_anchor_layout(
            table,
            width=width,
            height=height,
            background_color=background_color,
            random_state=random_state,
            colormap=colormap,
        )
        if use_physics
        else None
    )
    simulator = (
        _build_physics_simulator(
            layout,
            anchor_layout=anchor_layout,
            canvas_size=(width, height),
            config=physics_config,
        )
        if use_physics
        else None
    )
    peak_values = table.peak_values()

    for frame in iter_timeline_frames(
        table,
        frames_per_transition=frames_per_transition,
        interpolation=interpolation,
    ):
        frame_path = output / f"frame_{frame.index:04d}.png"
        centers = (
            simulator.step(frame.values, peak_values)
            if simulator is not None
            else None
        )
        render_fixed_frame(
            table,
            layout,
            frame.values,
            frame_path,
            background_color=background_color,
            min_font_size=min_font_size,
            centers=centers,
            label_text=label_for_frame(frame, label_config),
            label_config=label_config,
        )
        frame_paths.append(frame_path)

    return frame_paths


def _clear_animation_frames(output_dir: Path) -> None:
    for frame_path in output_dir.glob("frame_*.png"):
        frame_path.unlink(missing_ok=True)


def _build_anchor_layout(
    table: KeyframeTable,
    *,
    width: int,
    height: int,
    background_color: str,
    random_state: int,
    colormap: str,
) -> CloudLayout:
    return build_layout_from_frequencies(
        table.frame_values(table.frames[0]),
        explicit_colors=table.word_colors or {},
        word_groups=table.word_groups or {},
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
    )


def _build_physics_simulator(
    layout: CloudLayout,
    *,
    anchor_layout: CloudLayout | None,
    canvas_size: tuple[int, int],
    config: PhysicsConfig | None,
) -> PhysicsSimulator:
    font_path = getattr(layout.wordcloud, "font_path")
    peak_sizes = _measure_peak_sizes(layout, font_path=font_path)
    peak_centers = _layout_centers(layout, peak_sizes)
    anchor_centers = peak_centers
    if anchor_layout is not None:
        anchor_font_path = getattr(anchor_layout.wordcloud, "font_path")
        anchor_sizes = _measure_peak_sizes(anchor_layout, font_path=anchor_font_path)
        anchor_centers = {
            **peak_centers,
            **_layout_centers(anchor_layout, anchor_sizes),
        }

    specs = [
        WordBodySpec(
            word=word_layout.word,
            anchor=anchor_centers[word_layout.word],
            peak_size=peak_sizes[word_layout.word],
        )
        for word_layout in layout.words
    ]
    return PhysicsSimulator(specs, canvas_size=canvas_size, config=config)


def _measure_peak_sizes(
    layout: CloudLayout,
    *,
    font_path: str,
) -> dict[str, tuple[int, int]]:
    return {
        word_layout.word: _measure_word(
            word_layout.word,
            font_path=font_path,
            font_size=word_layout.font_size,
            orientation=word_layout.orientation,
        )
        for word_layout in layout.words
    }


def _layout_centers(
    layout: CloudLayout,
    peak_sizes: Mapping[str, tuple[int, int]],
) -> dict[str, tuple[float, float]]:
    centers: dict[str, tuple[float, float]] = {}
    for word_layout in layout.words:
        top, left = word_layout.position
        peak_width, peak_height = peak_sizes[word_layout.word]
        centers[word_layout.word] = (
            left + peak_width / 2.0,
            top + peak_height / 2.0,
        )

    return centers


def _measure_word(
    word: str,
    *,
    font_path: str,
    font_size: int,
    orientation: int | None,
) -> tuple[int, int]:
    word_image = _render_word_image(
        word,
        font_path=font_path,
        font_size=font_size,
        orientation=orientation,
        color="#000000",
    )
    return word_image.size


def _render_word_image(
    word: str,
    *,
    font_path: str,
    font_size: int,
    orientation: int | None,
    color: str,
) -> Image.Image:
    font = ImageFont.truetype(font_path, font_size)
    transposed_font = ImageFont.TransposedFont(font, orientation=orientation)

    scratch = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    scratch_draw = ImageDraw.Draw(scratch)
    bbox = scratch_draw.textbbox((0, 0), word, font=transposed_font)
    width = max(1, int(bbox[2] - bbox[0]))
    height = max(1, int(bbox[3] - bbox[1]))

    image = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.text((-bbox[0], -bbox[1]), word, fill=color, font=transposed_font)
    return image
