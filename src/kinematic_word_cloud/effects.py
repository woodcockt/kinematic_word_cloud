"""Raster post-processing effects for rendered word-cloud frames."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from PIL import Image, ImageChops, ImageColor, ImageFilter


BLOOM_SOURCES: tuple[str, ...] = ("edge", "fill")
BLOOM_INTENSITY_MODES: tuple[str, ...] = ("absolute", "relative", "constant")


@dataclass(frozen=True)
class BloomConfig:
    """Configuration for a per-word raster bloom effect."""

    radius_scale: float = 0.08
    min_radius: float = 1.5
    max_radius: float = 18.0
    strength: float = 2.0
    layers: int = 2
    color: str | None = None
    source: str = "edge"
    edge_width: int = 2
    intensity_mode: str = "absolute"
    intensity_power: float = 1.0

    def radius_for_font_size(self, font_size: float) -> float:
        """Return the blur radius for a rendered word size."""

        return max(
            self.min_radius,
            min(self.max_radius, font_size * self.radius_scale),
        )

    def strength_for_radius(self, radius: float, peak_radius: float) -> float:
        """Return bloom strength scaled by the configured size model."""

        if self.intensity_mode == "constant" or self.intensity_power == 0:
            return self.strength
        if self.intensity_mode == "absolute":
            radius_ratio = max(0.0, min(1.0, radius / self.max_radius))
            return self.strength * (radius_ratio**self.intensity_power)
        if peak_radius <= 0:
            return self.strength
        radius_ratio = max(0.0, min(1.0, radius / peak_radius))
        return self.strength * (radius_ratio**self.intensity_power)


def render_word_bloom(
    word_image: Image.Image,
    *,
    radius: float,
    strength: float,
    layers: int,
    color: str | None = None,
    source: str = "edge",
    edge_width: int = 1,
) -> tuple[Image.Image, int]:
    """Return a padded bloom image and the padding offset around a word."""

    safe_radius = max(0.0, float(radius))
    safe_strength = max(0.0, float(strength))
    safe_layers = max(1, int(layers))
    max_layer_radius = safe_radius * safe_layers
    padding = max(1, int(ceil(max_layer_radius * 3)))
    source_image = Image.new(
        "RGBA",
        (word_image.width + padding * 2, word_image.height + padding * 2),
        (255, 255, 255, 0),
    )
    source_image.alpha_composite(word_image.convert("RGBA"), (padding, padding))
    if source == "edge":
        source_image = _with_edge_alpha(
            source_image,
            width=edge_width,
        )
    elif source != "fill":
        raise ValueError(f"Unsupported bloom source: {source!r}")

    if color is not None:
        source_image = _tint_alpha(source_image, color)

    bloom = Image.new("RGBA", source_image.size, (255, 255, 255, 0))
    for index in range(safe_layers):
        layer_radius = safe_radius * (index + 1)
        layer_strength = safe_strength / (index + 1)
        blurred = source_image.filter(ImageFilter.GaussianBlur(layer_radius))
        bloom = Image.alpha_composite(bloom, _scale_alpha(blurred, layer_strength))

    return bloom, padding


def _scale_alpha(image: Image.Image, factor: float) -> Image.Image:
    """Return an RGBA image with alpha multiplied by factor."""

    if factor == 1:
        return image

    red, green, blue, alpha = image.convert("RGBA").split()
    scaled_alpha = alpha.point(
        lambda value: max(0, min(255, int(round(value * factor))))
    )
    return Image.merge("RGBA", (red, green, blue, scaled_alpha))


def _tint_alpha(image: Image.Image, color: str) -> Image.Image:
    """Return an RGBA image using the input alpha mask and a solid color."""

    red, green, blue = ImageColor.getrgb(color)[:3]
    alpha = image.convert("RGBA").getchannel("A")
    color_layer = Image.new("RGBA", image.size, (red, green, blue, 0))
    color_layer.putalpha(alpha)
    return color_layer


def _with_edge_alpha(image: Image.Image, *, width: int) -> Image.Image:
    """Return an image whose alpha mask is only the text edge band."""

    alpha = image.convert("RGBA").getchannel("A")
    kernel_size = max(3, int(width) * 2 + 1)
    dilated = alpha.filter(ImageFilter.MaxFilter(kernel_size))
    eroded = alpha.filter(ImageFilter.MinFilter(kernel_size))
    outer_edge = ImageChops.subtract(dilated, alpha)
    inner_edge = ImageChops.subtract(alpha, eroded)
    edge_alpha = ImageChops.lighter(outer_edge, inner_edge)

    edge_image = image.copy()
    edge_image.putalpha(edge_alpha)
    return edge_image
