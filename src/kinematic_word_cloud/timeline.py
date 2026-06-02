"""Value interpolation between keyframes."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Iterator, Literal

from .data import KeyframeDataError, KeyframeTable


InterpolationMode = Literal[
    "linear",
    "smoothstep",
    "rapid",
    "rapid10",
    "rapid25",
    "rapid50",
    "bounce",
    "catmull-rom",
    "monotone-cubic",
]
DEFAULT_INTERPOLATION: InterpolationMode = "linear"
INTERPOLATION_MODES: tuple[str, ...] = (
    "linear",
    "smoothstep",
    "rapid",
    "rapid10",
    "rapid25",
    "rapid50",
    "bounce",
    "catmull-rom",
    "monotone-cubic",
)
RAPID_ACTIVE_FRACTIONS: dict[str, float] = {
    "rapid": 0.25,
    "rapid10": 0.10,
    "rapid25": 0.25,
    "rapid50": 0.50,
}
BOUNCE_OVERSHOOT = 0.18
BOUNCE_OVERSHOOT_PHASE = 0.20
BOUNCE_SETTLE_PHASE = 0.50


@dataclass(frozen=True)
class TimelineFrame:
    """Interpolated word values for one rendered animation frame."""

    index: int
    position: float
    start_keyframe: str
    end_keyframe: str
    phase: float
    interpolated_phase: float
    values: dict[str, float]


def interpolate_values(
    table: KeyframeTable,
    position: float,
    *,
    interpolation: str = DEFAULT_INTERPOLATION,
) -> dict[str, float]:
    """Interpolate word values at a fractional keyframe position.

    `position=0.0` is the first keyframe, `position=1.0` is the second keyframe,
    and `position=0.5` is halfway between them.
    """

    return _build_frame(
        table,
        index=0,
        position=position,
        interpolation=interpolation,
    ).values


def iter_timeline_frames(
    table: KeyframeTable,
    *,
    frames_per_transition: int,
    interpolation: str = DEFAULT_INTERPOLATION,
) -> Iterator[TimelineFrame]:
    """Yield interpolated frames across all adjacent keyframes."""

    if frames_per_transition < 1:
        raise KeyframeDataError("frames_per_transition must be at least 1.")
    _validate_interpolation(interpolation)

    frame_index = 0
    for segment_index in range(table.frame_count - 1):
        for step in range(frames_per_transition):
            phase = step / float(frames_per_transition)
            position = segment_index + phase
            yield _build_frame(
                table,
                index=frame_index,
                position=position,
                interpolation=interpolation,
            )
            frame_index += 1

    final_position = float(table.frame_count - 1)
    yield _build_frame(
        table,
        index=frame_index,
        position=final_position,
        interpolation=interpolation,
    )


def timeline_frame_count(
    table: KeyframeTable,
    *,
    frames_per_transition: int,
) -> int:
    """Return the number of rendered frames for a complete timeline."""

    if frames_per_transition < 1:
        raise KeyframeDataError("frames_per_transition must be at least 1.")
    if table.frame_count < 2:
        raise KeyframeDataError("At least two keyframes are required.")

    return (table.frame_count - 1) * frames_per_transition + 1


def _build_frame(
    table: KeyframeTable,
    *,
    index: int,
    position: float,
    interpolation: str,
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
    if interpolation == "catmull-rom":
        interpolated_phase = phase
        interpolated = _catmull_rom_values(
            table,
            start_index=start_index,
            end_index=end_index,
            phase=phase,
        )
    elif interpolation == "monotone-cubic":
        interpolated_phase = phase
        interpolated = _monotone_cubic_values(
            table,
            start_index=start_index,
            end_index=end_index,
            phase=phase,
        )
    else:
        interpolated_phase = _interpolate_phase(phase, interpolation)
        start_values = table.values.iloc[:, start_index]
        end_values = table.values.iloc[:, end_index]
        interpolated = start_values + (end_values - start_values) * interpolated_phase
        if interpolation == "bounce":
            interpolated = interpolated.clip(lower=0.0)

    return TimelineFrame(
        index=index,
        position=position,
        start_keyframe=table.frames[start_index],
        end_keyframe=table.frames[end_index],
        phase=phase,
        interpolated_phase=interpolated_phase,
        values={
            str(word): float(value)
            for word, value in interpolated.items()
        },
    )


def _interpolate_phase(phase: float, interpolation: str) -> float:
    _validate_interpolation(interpolation)
    if interpolation == "linear":
        return phase
    if interpolation in {"catmull-rom", "monotone-cubic"}:
        return phase
    if interpolation in RAPID_ACTIVE_FRACTIONS:
        return min(1.0, phase / RAPID_ACTIVE_FRACTIONS[interpolation])
    if interpolation == "bounce":
        return _bounce_phase(phase)
    return phase * phase * (3.0 - 2.0 * phase)


def _bounce_phase(phase: float) -> float:
    if phase <= BOUNCE_OVERSHOOT_PHASE:
        return (1.0 + BOUNCE_OVERSHOOT) * phase / BOUNCE_OVERSHOOT_PHASE
    if phase <= BOUNCE_SETTLE_PHASE:
        local_phase = (
            (phase - BOUNCE_OVERSHOOT_PHASE)
            / (BOUNCE_SETTLE_PHASE - BOUNCE_OVERSHOOT_PHASE)
        )
        eased_phase = local_phase * local_phase * (3.0 - 2.0 * local_phase)
        return (1.0 + BOUNCE_OVERSHOOT) - BOUNCE_OVERSHOOT * eased_phase
    return 1.0


def _catmull_rom_values(
    table: KeyframeTable,
    *,
    start_index: int,
    end_index: int,
    phase: float,
):
    previous_index = max(0, start_index - 1)
    following_index = min(table.frame_count - 1, end_index + 1)
    p0 = table.values.iloc[:, previous_index]
    p1 = table.values.iloc[:, start_index]
    p2 = table.values.iloc[:, end_index]
    p3 = table.values.iloc[:, following_index]
    t2 = phase * phase
    t3 = t2 * phase

    interpolated = 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * phase
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )
    return interpolated.clip(lower=0.0)


def _monotone_cubic_values(
    table: KeyframeTable,
    *,
    start_index: int,
    end_index: int,
    phase: float,
):
    if start_index == end_index:
        return table.values.iloc[:, start_index]

    start_values = table.values.iloc[:, start_index]
    end_values = table.values.iloc[:, end_index]
    start_tangent = _monotone_tangent(table, start_index)
    end_tangent = _monotone_tangent(table, end_index)
    t2 = phase * phase
    t3 = t2 * phase

    interpolated = (
        (2.0 * t3 - 3.0 * t2 + 1.0) * start_values
        + (t3 - 2.0 * t2 + phase) * start_tangent
        + (-2.0 * t3 + 3.0 * t2) * end_values
        + (t3 - t2) * end_tangent
    )
    lower = start_values.where(start_values <= end_values, end_values)
    upper = start_values.where(start_values >= end_values, end_values)
    bounded = interpolated.where(interpolated >= lower, lower)
    bounded = bounded.where(bounded <= upper, upper)
    return bounded.clip(lower=0.0)


def _monotone_tangent(table: KeyframeTable, keyframe_index: int):
    if table.frame_count == 2:
        return table.values.iloc[:, 1] - table.values.iloc[:, 0]
    if keyframe_index == 0:
        return table.values.iloc[:, 1] - table.values.iloc[:, 0]
    if keyframe_index == table.frame_count - 1:
        return table.values.iloc[:, -1] - table.values.iloc[:, -2]

    previous_delta = (
        table.values.iloc[:, keyframe_index]
        - table.values.iloc[:, keyframe_index - 1]
    )
    next_delta = (
        table.values.iloc[:, keyframe_index + 1]
        - table.values.iloc[:, keyframe_index]
    )
    same_direction = previous_delta * next_delta > 0
    denominator = (previous_delta + next_delta).where(same_direction, 1.0)
    harmonic_mean = (
        2.0
        * previous_delta
        * next_delta
        / denominator
    )
    return harmonic_mean.where(same_direction, 0.0)


def _validate_interpolation(interpolation: str) -> None:
    if interpolation not in INTERPOLATION_MODES:
        raise KeyframeDataError(
            f"interpolation must be one of: {', '.join(INTERPOLATION_MODES)}"
        )
