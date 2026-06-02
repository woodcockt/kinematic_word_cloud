"""Absolute keyframe-transition change colors for animated word clouds."""

from __future__ import annotations

from typing import Mapping


DEFAULT_ABSOLUTECHANGE_GROWTH_COLOR = "#2EAD4D"
DEFAULT_ABSOLUTECHANGE_DECLINE_COLOR = "#D62828"
DEFAULT_ABSOLUTECHANGE_NO_CHANGE_COLOR = "#F2C94C"
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
