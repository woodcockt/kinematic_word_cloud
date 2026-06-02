"""Keyframe-transition change colors for animated word clouds."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Mapping


DEFAULT_ABSOLUTECHANGE_GROWTH_COLOR = "#2EAD4D"
DEFAULT_ABSOLUTECHANGE_DECLINE_COLOR = "#D62828"
DEFAULT_ABSOLUTECHANGE_NO_CHANGE_COLOR = "#F2C94C"
DEFAULT_SCALEDCHANGE_COLORS = (
    DEFAULT_ABSOLUTECHANGE_DECLINE_COLOR,
    DEFAULT_ABSOLUTECHANGE_NO_CHANGE_COLOR,
    DEFAULT_ABSOLUTECHANGE_GROWTH_COLOR,
)
CHANGE_COLOR_EPSILON = 1e-9


def color_for_absolute_change(
    word: str,
    start_values: Mapping[str, float],
    end_values: Mapping[str, float],
    *,
    growth_color: str = DEFAULT_ABSOLUTECHANGE_GROWTH_COLOR,
    decline_color: str = DEFAULT_ABSOLUTECHANGE_DECLINE_COLOR,
    no_change_color: str = DEFAULT_ABSOLUTECHANGE_NO_CHANGE_COLOR,
) -> str:
    """Return a color based on a word's absolute keyframe transition."""

    start_value = float(start_values.get(word, 0.0))
    end_value = float(end_values.get(word, 0.0))
    delta = end_value - start_value
    if delta > CHANGE_COLOR_EPSILON:
        return growth_color
    if delta < -CHANGE_COLOR_EPSILON:
        return decline_color
    return no_change_color


def color_for_scaled_change(
    word: str,
    start_values: Mapping[str, float],
    end_values: Mapping[str, float],
    *,
    max_absolute_change: float,
    colors: tuple[str, ...] = DEFAULT_SCALEDCHANGE_COLORS,
) -> str:
    """Return a ramp color based on signed keyframe-transition magnitude."""

    if max_absolute_change <= CHANGE_COLOR_EPSILON:
        normalized_delta = 0.0
    else:
        start_value = float(start_values.get(word, 0.0))
        end_value = float(end_values.get(word, 0.0))
        normalized_delta = (end_value - start_value) / max_absolute_change

    return interpolate_color_scale(normalized_delta, colors)


def max_absolute_change(
    frame_values: Iterable[Mapping[str, float]],
) -> float:
    """Return the largest absolute adjacent-frame delta in a frame sequence."""

    previous_values: Mapping[str, float] | None = None
    max_delta = 0.0
    for values in frame_values:
        if previous_values is None:
            previous_values = values
            continue

        words = set(previous_values) | set(values)
        for word in words:
            current_value = float(values.get(word, 0.0))
            previous_value = float(previous_values.get(word, 0.0))
            delta = abs(current_value - previous_value)
            max_delta = max(max_delta, delta)
        previous_values = values

    return max_delta


def interpolate_color_scale(value: float, colors: tuple[str, ...]) -> str:
    """Interpolate ordered color stops over a normalized -1 to +1 range."""

    if not colors:
        raise ValueError("Color scale must contain at least one color.")
    if len(colors) == 1:
        return colors[0]

    position = (max(-1.0, min(1.0, value)) + 1.0) / 2.0
    scaled_position = position * (len(colors) - 1)
    left_index = min(int(scaled_position), len(colors) - 2)
    right_index = left_index + 1
    local_t = scaled_position - left_index
    eased_t = local_t * local_t * (3.0 - 2.0 * local_t)
    left_rgb = _hex_to_rgb(colors[left_index])
    right_rgb = _hex_to_rgb(colors[right_index])
    blended = tuple(
        round(left + (right - left) * eased_t)
        for left, right in zip(left_rgb, right_rgb, strict=True)
    )
    return _rgb_to_hex(blended)


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    text = color.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(character * 2 for character in text)
    if len(text) != 6:
        raise ValueError(f"Expected #RGB or #RRGGBB color, got {color!r}.")
    return (
        int(text[0:2], 16),
        int(text[2:4], 16),
        int(text[4:6], 16),
    )


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#" + "".join(f"{channel:02X}" for channel in rgb)
