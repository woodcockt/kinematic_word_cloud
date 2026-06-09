"""Frame rendering utilities."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont

from .background import is_transparent_background, pillow_background_fill
from .change_color import (
    color_for_absolute_change,
    color_for_scaled_change,
    max_absolute_change,
)
from .config import DEFAULT_CANVAS_SIZE
from .data import KeyframeDataError, KeyframeTable
from .effects import BloomConfig, render_word_bloom
from .labels import LabelConfig, label_for_frame, render_label_overlay
from .layout import (
    ABSOLUTECHANGE_COLOR_BY,
    CloudLayout,
    ColorOptions,
    SCALEDCHANGE_COLOR_BY,
    build_layout_from_frequencies,
    build_peak_layout,
)
from .physics import PhysicsConfig, PhysicsSimulator, WordBodySpec
from .timeline import DEFAULT_INTERPOLATION, iter_timeline_frames


@dataclass(frozen=True)
class ImageFrameItem:
    """A raster image item to composite into one rendered frame."""

    item_id: str
    image: Image.Image
    center: tuple[float, float]
    current_value: float
    peak_value: float
    peak_size: tuple[int, int]
    layer: str = "front"


def render_peak_cloud(
    table: KeyframeTable,
    output_path: str | Path,
    *,
    width: int = DEFAULT_CANVAS_SIZE.width,
    height: int = DEFAULT_CANVAS_SIZE.height,
    background_color: str = "white",
    random_state: int = 42,
    colormap: str = "viridis",
    color_options: ColorOptions | None = None,
) -> CloudLayout:
    """Render the peak-value starting cloud to an image file."""

    layout = build_peak_layout(
        table,
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
        color_options=color_options,
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
    bloom_config: BloomConfig | None = None,
    change_start_values: Mapping[str, float] | None = None,
    change_end_values: Mapping[str, float] | None = None,
    color_options: ColorOptions | None = None,
    scaledchange_max_absolute_change: float = 0.0,
    size_reference_values: Mapping[str, float] | None = None,
    size_max_value: float | None = None,
    image_items: tuple[ImageFrameItem, ...] = (),
) -> Image.Image:
    """Render one fixed-position frame with size scaled by current values."""

    wordcloud = layout.wordcloud
    image_mode = getattr(wordcloud, "mode", "RGB")
    background = (
        background_color
        if background_color is not None
        else getattr(wordcloud, "background_color", "white")
    )
    image = Image.new(
        "RGBA",
        (layout.width, layout.height),
        pillow_background_fill(background),
    )
    word_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    back_image_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    front_image_layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    bloom_layer = (
        Image.new("RGBA", image.size, (255, 255, 255, 0))
        if bloom_config is not None
        else None
    )
    font_path = getattr(wordcloud, "font_path")
    peak_values = size_reference_values or table.peak_values()
    peak_sizes = _measure_peak_sizes(layout, font_path=font_path)
    layout_centers = _layout_centers(layout, peak_sizes)

    for word_layout in layout.words:
        current_value = float(values.get(word_layout.word, 0.0))
        if size_max_value is not None:
            current_value = min(current_value, size_max_value)
        peak_value = peak_values.get(word_layout.word, 0.0)
        if current_value <= 0 or peak_value <= 0:
            continue

        scale = current_value / peak_value
        scaled_font_size = word_layout.font_size * scale
        font_size = max(min_font_size, int(round(scaled_font_size)))
        word_color = word_layout.color
        if color_options is not None and color_options.color_by == ABSOLUTECHANGE_COLOR_BY:
            word_color = color_for_absolute_change(
                word_layout.word,
                change_start_values or {},
                change_end_values or {},
                growth_color=color_options.absolutechange_growth_color,
                decline_color=color_options.absolutechange_decline_color,
                no_change_color=color_options.absolutechange_no_change_color,
            )
        elif color_options is not None and color_options.color_by == SCALEDCHANGE_COLOR_BY:
            word_color = color_for_scaled_change(
                word_layout.word,
                change_start_values or {},
                change_end_values or {},
                max_absolute_change=scaledchange_max_absolute_change,
                colors=color_options.scaledchange_colors,
            )
        current_image = _render_word_image(
            word_layout.word,
            font_path=font_path,
            font_size=font_size,
            orientation=word_layout.orientation,
            color=word_color,
        )

        center_x, center_y = (
            centers.get(word_layout.word, layout_centers[word_layout.word])
            if centers is not None
            else layout_centers[word_layout.word]
        )
        paste_x = int(round(center_x - current_image.width / 2))
        paste_y = int(round(center_y - current_image.height / 2))
        if bloom_layer is not None:
            radius = bloom_config.radius_for_font_size(
                max(float(min_font_size), scaled_font_size)
            )
            peak_radius = bloom_config.radius_for_font_size(word_layout.font_size)
            strength = bloom_config.strength_for_radius(radius, peak_radius)
            bloom_image, padding = render_word_bloom(
                current_image,
                radius=radius,
                strength=strength,
                layers=bloom_config.layers,
                color=bloom_config.color,
                source=bloom_config.source,
                edge_width=bloom_config.edge_width,
            )
            _alpha_composite_at(
                bloom_layer,
                bloom_image,
                (paste_x - padding, paste_y - padding),
            )
        _alpha_composite_at(word_layer, current_image, (paste_x, paste_y))

    for image_item in image_items:
        current_image = _render_image_item(image_item)
        if current_image is None:
            continue
        center_x, center_y = image_item.center
        paste_x = int(round(center_x - current_image.width / 2))
        paste_y = int(round(center_y - current_image.height / 2))
        target_layer = (
            back_image_layer if image_item.layer == "back" else front_image_layer
        )
        _alpha_composite_at(target_layer, current_image, (paste_x, paste_y))

    image = Image.alpha_composite(image, back_image_layer)
    if bloom_layer is not None:
        image = Image.alpha_composite(image, bloom_layer)
    image = Image.alpha_composite(image, word_layer)
    image = Image.alpha_composite(image, front_image_layer)

    render_label_overlay(
        image,
        label_text,
        config=label_config,
        font_path=font_path,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output_image = (
        image
        if image_mode == "RGBA" or is_transparent_background(background)
        else image.convert(image_mode)
    )
    output_image.save(output)
    return output_image


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
    color_options: ColorOptions | None = None,
    bloom_config: BloomConfig | None = None,
    size_max_value: float | None = None,
) -> list[Path]:
    """Render PNG frames for the whole keyframe timeline."""

    layout, size_reference_values = _build_size_reference_layout(
        table,
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
        color_options=color_options,
        size_max_value=size_max_value,
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
            color_options=color_options,
            size_reference_values=size_reference_values,
            size_max_value=size_max_value,
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

    for frame in iter_timeline_frames(
        table,
        frames_per_transition=frames_per_transition,
        interpolation=interpolation,
    ):
        frame_path = output / f"frame_{frame.index:04d}.png"
        physics_values = _clamp_values_to_size_max(frame.values, size_max_value)
        centers = (
            simulator.step(physics_values, size_reference_values)
            if simulator is not None
            else None
        )
        change_start_values = (
            table.frame_values(frame.start_keyframe)
            if uses_transition_colors
            else None
        )
        change_end_values = (
            table.frame_values(frame.end_keyframe)
            if uses_transition_colors
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
            bloom_config=bloom_config,
            change_start_values=change_start_values,
            change_end_values=change_end_values,
            color_options=color_options,
            scaledchange_max_absolute_change=scaledchange_max_absolute_change,
            size_reference_values=size_reference_values,
            size_max_value=size_max_value,
        )
        frame_paths.append(frame_path)

    return frame_paths


def _clear_animation_frames(output_dir: Path) -> None:
    for frame_path in output_dir.glob("frame_*.png"):
        frame_path.unlink(missing_ok=True)


def _build_size_reference_layout(
    table: KeyframeTable,
    *,
    width: int,
    height: int,
    background_color: str,
    random_state: int,
    colormap: str,
    color_options: ColorOptions | None,
    size_max_value: float | None,
) -> tuple[CloudLayout, dict[str, float]]:
    size_reference_values = _size_reference_values(table, size_max_value)
    layout = build_layout_from_frequencies(
        size_reference_values,
        explicit_colors=table.word_colors or {},
        word_groups=table.word_groups or {},
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
        color_options=color_options,
    )
    return (
        _scale_layout_font_sizes(
            layout,
            _layout_font_scale(size_reference_values, size_max_value),
        ),
        size_reference_values,
    )


def _size_reference_values(
    table: KeyframeTable,
    size_max_value: float | None,
) -> dict[str, float]:
    peak_values = table.peak_values()
    if size_max_value is None:
        return peak_values

    return {
        word: min(value, size_max_value) if value > 0 else 0.0
        for word, value in peak_values.items()
    }


def _layout_font_scale(
    size_reference_values: Mapping[str, float],
    size_max_value: float | None,
) -> float:
    if size_max_value is None:
        return 1.0

    max_reference = max(size_reference_values.values(), default=0.0)
    if max_reference <= 0:
        return 1.0
    return min(max_reference / size_max_value, 1.0)


def _scale_layout_font_sizes(layout: CloudLayout, scale: float) -> CloudLayout:
    if scale >= 1.0:
        return layout

    font_path = getattr(layout.wordcloud, "font_path")
    scaled_words = []
    for word_layout in layout.words:
        old_width, old_height = _measure_word(
            word_layout.word,
            font_path=font_path,
            font_size=word_layout.font_size,
            orientation=word_layout.orientation,
        )
        scaled_font_size = max(1, int(round(word_layout.font_size * scale)))
        new_width, new_height = _measure_word(
            word_layout.word,
            font_path=font_path,
            font_size=scaled_font_size,
            orientation=word_layout.orientation,
        )
        top, left = word_layout.position
        scaled_words.append(
            replace(
                word_layout,
                font_size=scaled_font_size,
                position=(
                    int(round(top + (old_height - new_height) / 2.0)),
                    int(round(left + (old_width - new_width) / 2.0)),
                ),
            )
        )

    return replace(layout, words=tuple(scaled_words))


def _clamp_values_to_size_max(
    values: Mapping[str, float],
    size_max_value: float | None,
) -> Mapping[str, float]:
    if size_max_value is None:
        return values

    return {
        word: min(float(value), size_max_value)
        for word, value in values.items()
    }


def _build_anchor_layout(
    table: KeyframeTable,
    *,
    width: int,
    height: int,
    background_color: str,
    random_state: int,
    colormap: str,
    color_options: ColorOptions | None,
    size_reference_values: Mapping[str, float],
    size_max_value: float | None,
) -> CloudLayout:
    anchor_values = table.frame_values(table.frames[0])
    if not any(value > 0 for value in anchor_values.values()):
        anchor_values = dict(size_reference_values)
    else:
        anchor_values = dict(_clamp_values_to_size_max(anchor_values, size_max_value))

    layout = build_layout_from_frequencies(
        anchor_values,
        explicit_colors=table.word_colors or {},
        word_groups=table.word_groups or {},
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
        color_options=color_options,
    )
    return _scale_layout_font_sizes(
        layout,
        _layout_font_scale(anchor_values, size_max_value),
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


def _alpha_composite_at(
    base: Image.Image,
    overlay: Image.Image,
    position: tuple[int, int],
) -> None:
    """Alpha-composite an overlay into a base image, cropping at boundaries."""

    paste_x, paste_y = position
    source_left = max(0, -paste_x)
    source_top = max(0, -paste_y)
    source_right = min(overlay.width, base.width - paste_x)
    source_bottom = min(overlay.height, base.height - paste_y)
    if source_right <= source_left or source_bottom <= source_top:
        return

    cropped = overlay.crop((source_left, source_top, source_right, source_bottom))
    base.alpha_composite(
        cropped,
        (max(0, paste_x), max(0, paste_y)),
    )


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


def _render_image_item(item: ImageFrameItem) -> Image.Image | None:
    current_value = float(item.current_value)
    peak_value = float(item.peak_value)
    if current_value <= 0 or peak_value <= 0:
        return None

    scale = current_value / peak_value
    if scale <= 0:
        return None

    image = item.image.convert("RGBA")
    width = max(1, int(round(item.peak_size[0] * scale)))
    height = max(1, int(round(item.peak_size[1] * scale)))
    try:
        resampling = Image.Resampling.LANCZOS
    except AttributeError:  # pragma: no cover - Pillow < 9 compatibility.
        resampling = Image.LANCZOS
    try:
        return image.resize((width, height), resampling)
    except ValueError as exc:
        raise KeyframeDataError(
            f"Could not resize image asset for item {item.item_id!r}."
        ) from exc
