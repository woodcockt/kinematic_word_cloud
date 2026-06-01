"""Load and validate tabular word-cloud keyframe data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import pandas as pd


DEFAULT_WORD_COLUMN = "word"
DEFAULT_COLOR_COLUMN = "color"
DEFAULT_GROUP_COLUMN = "group"
HEX_COLOR_PATTERN = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class KeyframeDataError(ValueError):
    """Raised when keyframe input cannot be normalized safely."""


@dataclass(frozen=True)
class KeyframeTable:
    """A normalized word-by-frame value matrix.

    The underlying dataframe uses words as the index and frame labels as
    columns. Values are non-negative floats.
    """

    values: pd.DataFrame
    source: Path | None = None
    word_colors: dict[str, str] | None = None
    word_groups: dict[str, str] | None = None

    @property
    def words(self) -> list[str]:
        """Words in the order supplied by the input table."""

        return [str(word) for word in self.values.index]

    @property
    def frames(self) -> list[str]:
        """Frame labels in the order supplied by the input table."""

        return [str(frame) for frame in self.values.columns]

    @property
    def frame_count(self) -> int:
        """Number of keyframes in the table."""

        return len(self.values.columns)

    @property
    def word_count(self) -> int:
        """Number of words in the table."""

        return len(self.values.index)

    def peak_values(self) -> dict[str, float]:
        """Return each word's maximum value across all keyframes."""

        return {
            str(word): float(value)
            for word, value in self.values.max(axis=1).items()
        }

    def frame_values(self, frame: str) -> dict[str, float]:
        """Return word values for a single frame label."""

        if frame not in self.values.columns:
            raise KeyframeDataError(f"Unknown frame label: {frame!r}")

        return {
            str(word): float(value)
            for word, value in self.values[frame].items()
        }

    def color_for_word(self, word: str) -> str | None:
        """Return an explicit hex color for a word, if one was supplied."""

        return (self.word_colors or {}).get(word)

    def group_for_word(self, word: str) -> str | None:
        """Return a group label for a word, if one was supplied."""

        return (self.word_groups or {}).get(word)

    def to_wide_dataframe(
        self,
        word_column: str = DEFAULT_WORD_COLUMN,
        *,
        include_metadata: bool = True,
        color_column: str = DEFAULT_COLOR_COLUMN,
        group_column: str = DEFAULT_GROUP_COLUMN,
    ) -> pd.DataFrame:
        """Return a wide dataframe with a word column followed by frame columns."""

        dataframe = self.values.reset_index(names=word_column)
        if not include_metadata:
            return dataframe

        if self.word_groups:
            dataframe.insert(
                1,
                group_column,
                dataframe[word_column].map(lambda word: self.word_groups.get(word, "")),
            )
        if self.word_colors:
            dataframe.insert(
                1,
                color_column,
                dataframe[word_column].map(lambda word: self.word_colors.get(word, "")),
            )

        return dataframe


def load_keyframes(
    path: str | Path,
    *,
    word_column: str = DEFAULT_WORD_COLUMN,
    color_column: str = DEFAULT_COLOR_COLUMN,
    group_column: str = DEFAULT_GROUP_COLUMN,
) -> KeyframeTable:
    """Load a wide CSV keyframe table from disk.

    Expected shape:

    ```csv
    word,color,group,2026-01,2026-02,2026-03
    python,#3776AB,language,100,50,12
    animation,,motion,8,38,100
    ```
    """

    source = Path(path)
    if source.suffix.lower() != ".csv":
        raise KeyframeDataError(f"Expected a CSV file, got: {source}")

    try:
        dataframe = pd.read_csv(source)
    except FileNotFoundError as exc:
        raise KeyframeDataError(f"Keyframe CSV not found: {source}") from exc
    except pd.errors.EmptyDataError as exc:
        raise KeyframeDataError(f"Keyframe CSV is empty: {source}") from exc

    return from_wide_dataframe(
        dataframe,
        word_column=word_column,
        color_column=color_column,
        group_column=group_column,
        source=source,
    )


def from_wide_dataframe(
    dataframe: pd.DataFrame,
    *,
    word_column: str = DEFAULT_WORD_COLUMN,
    color_column: str = DEFAULT_COLOR_COLUMN,
    group_column: str = DEFAULT_GROUP_COLUMN,
    source: str | Path | None = None,
) -> KeyframeTable:
    """Normalize and validate a wide keyframe dataframe."""

    if dataframe.empty:
        raise KeyframeDataError("Keyframe table must contain at least one word.")

    normalized = dataframe.copy()
    normalized.columns = [_clean_column_name(column) for column in normalized.columns]
    word_column = _clean_column_name(word_column)
    color_column = _clean_column_name(color_column)
    group_column = _clean_column_name(group_column)

    if word_column not in normalized.columns:
        raise KeyframeDataError(f"Missing required word column: {word_column!r}")

    metadata_columns = {word_column, color_column, group_column}
    frame_columns = [
        column for column in normalized.columns if column not in metadata_columns
    ]
    if len(frame_columns) < 2:
        raise KeyframeDataError("Keyframe table must contain at least two frame columns.")

    _validate_unique(frame_columns, label="frame column")

    words = normalized[word_column].map(_clean_word)
    if words.isna().any():
        raise KeyframeDataError("Word column contains blank or missing values.")
    _validate_unique(words.tolist(), label="word")

    word_colors = _read_optional_colors(normalized, words, color_column)
    word_groups = _read_optional_groups(normalized, words, group_column)

    values = normalized.loc[:, frame_columns].apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any():
        bad_columns = values.columns[values.isna().any()].tolist()
        raise KeyframeDataError(
            "Frame values must be numeric. Invalid values found in: "
            + ", ".join(map(str, bad_columns))
        )

    if (values < 0).any().any():
        raise KeyframeDataError("Frame values must be non-negative.")

    if float(values.to_numpy().sum()) == 0:
        raise KeyframeDataError("At least one frame value must be greater than zero.")

    values.index = words
    values.index.name = word_column

    return KeyframeTable(
        values=values.astype(float),
        source=Path(source) if source is not None else None,
        word_colors=word_colors,
        word_groups=word_groups,
    )


def _clean_column_name(value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise KeyframeDataError("Column names cannot be blank.")
    return text


def _clean_word(value: Any) -> str | None:
    if pd.isna(value):
        return None

    text = str(value).strip()
    return text or None


def _read_optional_colors(
    dataframe: pd.DataFrame,
    words: pd.Series,
    color_column: str,
) -> dict[str, str]:
    if color_column not in dataframe.columns:
        return {}

    colors: dict[str, str] = {}
    for word, raw_color in zip(words, dataframe[color_column], strict=True):
        color = _clean_hex_color(raw_color, word=word)
        if color is not None:
            colors[word] = color

    return colors


def _read_optional_groups(
    dataframe: pd.DataFrame,
    words: pd.Series,
    group_column: str,
) -> dict[str, str]:
    if group_column not in dataframe.columns:
        return {}

    groups: dict[str, str] = {}
    for word, raw_group in zip(words, dataframe[group_column], strict=True):
        group = _clean_optional_text(raw_group)
        if group is not None:
            groups[word] = group

    return groups


def _clean_hex_color(value: Any, *, word: str) -> str | None:
    text = _clean_optional_text(value)
    if text is None:
        return None

    match = HEX_COLOR_PATTERN.match(text)
    if match is None:
        raise KeyframeDataError(
            f"Invalid hex color for word {word!r}: {text!r}. "
            "Expected #RGB or #RRGGBB."
        )

    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(channel * 2 for channel in digits)

    return f"#{digits.upper()}"


def _clean_optional_text(value: Any) -> str | None:
    if pd.isna(value):
        return None

    text = str(value).strip()
    return text or None


def _validate_unique(values: list[str], *, label: str) -> None:
    seen: set[str] = set()
    duplicates: list[str] = []

    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)

    if duplicates:
        raise KeyframeDataError(
            f"Duplicate {label}s are not allowed: " + ", ".join(duplicates)
        )
