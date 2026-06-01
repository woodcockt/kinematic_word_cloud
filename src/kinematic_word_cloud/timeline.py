"""Value interpolation between keyframes."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterator

from .data import KeyframeDataError, KeyframeTable


@dataclass(frozen=True)
class TimelineFrame:
    """Interpolated word values for one rendered animation frame."""

    index: int
    position: float
    start_keyframe: str
    end_keyframe: str
    phase: float
    values: dict[str, float]


def interpolate_values(table: KeyframeTable, position: float) -> dict[str, float]:
    """Interpolate word values at a fractional keyframe position.

    `position=0.0` is the first keyframe, `position=1.0` is the second keyframe,
    and `position=0.5` is halfway between them.
    """

    return _build_frame(table, index=0, position=position).values


def iter_timeline_frames(
    table: KeyframeTable,
    *,
    frames_per_transition: int,
) -> Iterator[TimelineFrame]:
    """Yield interpolated frames across all adjacent keyframes."""

    if frames_per_transition < 1:
        raise KeyframeDataError("frames_per_transition must be at least 1.")

    frame_index = 0
    for segment_index in range(table.frame_count - 1):
        for step in range(frames_per_transition):
            phase = step / float(frames_per_transition)
            position = segment_index + phase
            yield _build_frame(table, index=frame_index, position=position)
            frame_index += 1

    final_position = float(table.frame_count - 1)
    yield _build_frame(table, index=frame_index, position=final_position)


def _build_frame(
    table: KeyframeTable,
    *,
    index: int,
    position: float,
) -> TimelineFrame:
    if table.frame_count < 2:
        raise KeyframeDataError("At least two keyframes are required.")

    max_position = table.frame_count - 1
    if position < 0 or position > max_position:
        raise KeyframeDataError(
            f"Timeline position must be between 0 and {max_position}, got {position}."
        )

    start_index = min(floor(position), max_position)
    end_index = min(start_index + 1, max_position)
    phase = 0.0 if start_index == end_index else position - start_index

    start_values = table.values.iloc[:, start_index]
    end_values = table.values.iloc[:, end_index]
    interpolated = start_values + (end_values - start_values) * phase

    return TimelineFrame(
        index=index,
        position=position,
        start_keyframe=table.frames[start_index],
        end_keyframe=table.frames[end_index],
        phase=phase,
        values={
            str(word): float(value)
            for word, value in interpolated.items()
        },
    )
