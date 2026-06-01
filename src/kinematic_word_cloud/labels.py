"""Overlay labels for word-cloud animations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .timeline import DEFAULT_INTERPOLATION, TimelineFrame, iter_timeline_frames


LabelMode = Literal["none", "keyframe"]
LabelPosition = Literal[
    "top-left",
    "top-center",
    "top-right",
    "center",
    "bottom-left",
    "bottom-center",
    "bottom-right",
]

LABEL_MODES: tuple[str, ...] = ("none", "keyframe")
LABEL_POSITIONS: tuple[str, ...] = (
    "top-left",
    "top-center",
    "top-right",
    "center",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)


@dataclass(frozen=True)
class LabelConfig:
    """Configuration for a non-colliding animation label overlay."""

    mode: LabelMode = "none"
    position: LabelPosition = "top-left"
    font_size: int = 56
    color: str = "#222222"
    opacity: float = 0.85
    margin: int = 32


def label_for_frame(
    frame: TimelineFrame,
    config: LabelConfig | None,
) -> str | None:
    """Return the overlay label for an interpolated frame."""

    if config is None or config.mode == "none":
        return None
    if config.mode == "keyframe":
        return frame.start_keyframe

    raise ValueError(f"Unsupported label mode: {config.mode!r}")


def sample_labels(
    table,
    *,
    frames_per_transition: int,
    config: LabelConfig | None,
    interpolation: str = DEFAULT_INTERPOLATION,
) -> list[str | None]:
    """Return the label value for every sampled animation frame."""

    return [
        label_for_frame(frame, config)
        for frame in iter_timeline_frames(
            table,
            frames_per_transition=frames_per_transition,
            interpolation=interpolation,
        )
    ]


def render_label_overlay(
    image: Image.Image,
    text: str | None,
    *,
    config: LabelConfig | None,
    font_path: str | None,
) -> None:
    """Draw a label over an existing Pillow image in place."""

    if text is None or config is None or config.mode == "none":
        return

    font = _load_font(font_path, config.font_size)
    layer = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(layer)
    bbox = draw.textbbox((0, 0), text, font=font)
    origin = _label_origin(
        image.size,
        bbox=bbox,
        position=config.position,
        margin=config.margin,
    )
    red, green, blue = ImageColor.getrgb(config.color)[:3]
    alpha = int(round(max(0.0, min(1.0, config.opacity)) * 255))
    draw.text(origin, text, font=font, fill=(red, green, blue, alpha))

    if image.mode != "RGBA":
        composited = Image.alpha_composite(image.convert("RGBA"), layer)
        image.paste(composited.convert(image.mode))
    else:
        image.alpha_composite(layer)


def svg_label_position(
    *,
    width: int,
    height: int,
    config: LabelConfig,
) -> tuple[float, float, str, str]:
    """Return SVG x/y plus anchor and baseline values for a label position."""

    horizontal, vertical = _split_position(config.position)
    if horizontal == "left":
        x = float(config.margin)
        anchor = "start"
    elif horizontal == "center":
        x = width / 2.0
        anchor = "middle"
    else:
        x = width - float(config.margin)
        anchor = "end"

    if vertical == "top":
        y = float(config.margin)
        baseline = "hanging"
    elif vertical == "center":
        y = height / 2.0
        baseline = "central"
    else:
        y = height - float(config.margin)
        baseline = "text-after-edge"

    return x, y, anchor, baseline


def _load_font(font_path: str | None, font_size: int) -> ImageFont.ImageFont:
    if font_path is None:
        return ImageFont.load_default()
    return ImageFont.truetype(font_path, font_size)


def _label_origin(
    size: tuple[int, int],
    *,
    bbox: tuple[int, int, int, int],
    position: LabelPosition,
    margin: int,
) -> tuple[float, float]:
    canvas_width, canvas_height = size
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    horizontal, vertical = _split_position(position)

    if horizontal == "left":
        x = margin - bbox[0]
    elif horizontal == "center":
        x = (canvas_width - text_width) / 2.0 - bbox[0]
    else:
        x = canvas_width - margin - text_width - bbox[0]

    if vertical == "top":
        y = margin - bbox[1]
    elif vertical == "center":
        y = (canvas_height - text_height) / 2.0 - bbox[1]
    else:
        y = canvas_height - margin - text_height - bbox[1]

    return x, y


def _split_position(position: LabelPosition) -> tuple[str, str]:
    if position == "center":
        return "center", "center"

    vertical, horizontal = position.split("-", maxsplit=1)
    return horizontal, vertical
