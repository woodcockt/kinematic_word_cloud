"""Background color helpers shared by layout and frame rendering."""

from __future__ import annotations

from typing import Any


TRANSPARENT_BACKGROUND = "transparent"
TRANSPARENT_RGBA = (0, 0, 0, 0)


def is_transparent_background(value: Any) -> bool:
    """Return true when a background value requests transparent pixels."""

    if value is None:
        return True
    return str(value).strip().lower() == TRANSPARENT_BACKGROUND


def pillow_background_fill(value: Any) -> Any:
    """Return a Pillow-compatible background fill value."""

    if is_transparent_background(value):
        return TRANSPARENT_RGBA
    return value


def wordcloud_background_color(value: Any) -> Any:
    """Return a WordCloud background value."""

    if is_transparent_background(value):
        return None
    return value


def wordcloud_mode(value: Any) -> str:
    """Return the WordCloud image mode for a background value."""

    return "RGBA" if is_transparent_background(value) else "RGB"
