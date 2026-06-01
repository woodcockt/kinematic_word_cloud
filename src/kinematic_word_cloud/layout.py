"""Word-cloud layout extraction and normalization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

try:
    from wordcloud import WordCloud
except ImportError:  # pragma: no cover - exercised when optional dep is missing.
    WordCloud = None

from .config import DEFAULT_CANVAS_SIZE
from .data import KeyframeTable


DEFAULT_COLOR_PALETTE = (
    "#3776AB",
    "#E76F51",
    "#2A9D8F",
    "#E9C46A",
    "#4A2C7A",
    "#F4A261",
    "#264653",
    "#C05780",
)
TABLEAU_COLOR_PALETTE = (
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
)
OKABE_ITO_COLOR_PALETTE = (
    "#0072B2",
    "#E69F00",
    "#009E73",
    "#D55E00",
    "#CC79A7",
    "#56B4E9",
    "#F0E442",
)
COLOR_PALETTES: dict[str, tuple[str, ...]] = {
    "default": DEFAULT_COLOR_PALETTE,
    "tableau": TABLEAU_COLOR_PALETTE,
    "okabe-ito": OKABE_ITO_COLOR_PALETTE,
}
DEFAULT_PALETTE_NAME = "default"
DEFAULT_COLOR_BY = "group"
COLOR_BY_MODES: tuple[str, ...] = ("group", "word", "single")
DEFAULT_FALLBACK_COLOR = "#222222"


@dataclass(frozen=True)
class ColorOptions:
    """Color assignment options for generated word-cloud layouts."""

    palette: tuple[str, ...] = DEFAULT_COLOR_PALETTE
    color_by: str = DEFAULT_COLOR_BY
    group_colors: Mapping[str, str] | None = None
    default_color: str = DEFAULT_FALLBACK_COLOR


@dataclass(frozen=True)
class WordLayout:
    """A single word placement produced by `wordcloud`."""

    word: str
    normalized_frequency: float
    font_size: int
    position: tuple[int, int]
    orientation: int | None
    color: str


@dataclass(frozen=True)
class CloudLayout:
    """A static word-cloud layout plus its rendered `WordCloud` object."""

    words: tuple[WordLayout, ...]
    wordcloud: object
    width: int
    height: int


def build_peak_layout(
    table: KeyframeTable,
    *,
    width: int = DEFAULT_CANVAS_SIZE.width,
    height: int = DEFAULT_CANVAS_SIZE.height,
    background_color: str = "white",
    random_state: int = 42,
    colormap: str = "viridis",
    prefer_horizontal: float = 0.95,
    color_palette: tuple[str, ...] = DEFAULT_COLOR_PALETTE,
    color_options: ColorOptions | None = None,
) -> CloudLayout:
    """Generate a static layout from each word's peak value."""

    return build_layout_from_frequencies(
        table.peak_values(),
        explicit_colors=table.word_colors or {},
        word_groups=table.word_groups or {},
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
        prefer_horizontal=prefer_horizontal,
        color_palette=color_palette,
        color_options=color_options,
    )


def build_layout_from_frequencies(
    frequencies: Mapping[str, float],
    *,
    explicit_colors: Mapping[str, str] | None = None,
    word_groups: Mapping[str, str] | None = None,
    width: int = DEFAULT_CANVAS_SIZE.width,
    height: int = DEFAULT_CANVAS_SIZE.height,
    background_color: str = "white",
    random_state: int = 42,
    colormap: str = "viridis",
    prefer_horizontal: float = 0.95,
    color_palette: tuple[str, ...] = DEFAULT_COLOR_PALETTE,
    color_options: ColorOptions | None = None,
) -> CloudLayout:
    """Generate a `wordcloud` layout from word frequencies."""

    if WordCloud is None:
        raise RuntimeError(
            "The 'wordcloud' package is required for layout generation. "
            "Install project dependencies with `python3 -m pip install -e .`."
        )

    positive_frequencies = {
        str(word): float(value)
        for word, value in frequencies.items()
        if float(value) > 0
    }
    if not positive_frequencies:
        raise ValueError("At least one frequency must be greater than zero.")

    color_func = build_color_func(
        explicit_colors=explicit_colors or {},
        word_groups=word_groups or {},
        color_palette=color_palette,
        color_options=color_options,
    )

    wordcloud = WordCloud(
        width=width,
        height=height,
        background_color=background_color,
        random_state=random_state,
        colormap=colormap,
        color_func=color_func,
        prefer_horizontal=prefer_horizontal,
    )
    wordcloud.generate_from_frequencies(positive_frequencies)

    return CloudLayout(
        words=tuple(_convert_layout_entry(entry) for entry in wordcloud.layout_),
        wordcloud=wordcloud,
        width=width,
        height=height,
    )


def build_color_func(
    *,
    explicit_colors: Mapping[str, str],
    word_groups: Mapping[str, str],
    color_palette: tuple[str, ...] = DEFAULT_COLOR_PALETTE,
    color_options: ColorOptions | None = None,
):
    """Build a deterministic `wordcloud` color function.

    Color precedence is:
    1. explicit word color,
    2. configured or deterministic group color when color_by="group",
    3. deterministic fallback color by word when color_by="group" or "word",
    4. neutral default color when color_by="single".
    """

    options = color_options or ColorOptions(palette=color_palette)
    if options.color_by not in COLOR_BY_MODES:
        raise ValueError(f"color_by must be one of: {', '.join(COLOR_BY_MODES)}")
    if not options.palette:
        raise ValueError("Color palette must contain at least one color.")

    group_colors = {
        **_assign_group_colors(word_groups.values(), options.palette),
        **{
            str(group): str(color)
            for group, color in (options.group_colors or {}).items()
        },
    }

    def color_func(word, *args, **kwargs):
        word = str(word)
        if word in explicit_colors:
            return explicit_colors[word]

        group = word_groups.get(word)
        if options.color_by == "group" and group is not None:
            return group_colors[group]

        if options.color_by in {"group", "word"}:
            return options.palette[_stable_index(word, len(options.palette))]

        return options.default_color

    return color_func


def _convert_layout_entry(entry: tuple) -> WordLayout:
    (word, normalized_frequency), font_size, position, orientation, color = entry

    return WordLayout(
        word=str(word),
        normalized_frequency=float(normalized_frequency),
        font_size=int(font_size),
        position=(int(position[0]), int(position[1])),
        orientation=orientation,
        color=str(color),
    )


def _assign_group_colors(
    groups: object,
    color_palette: tuple[str, ...],
) -> dict[str, str]:
    unique_groups = sorted({str(group) for group in groups if group is not None})
    return {
        group: color_palette[index % len(color_palette)]
        for index, group in enumerate(unique_groups)
    }


def _stable_index(value: str, modulo: int) -> int:
    return sum(ord(character) for character in value) % modulo
