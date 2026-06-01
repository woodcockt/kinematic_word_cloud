"""Runtime configuration helpers."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from .data import KeyframeDataError, KeyframeTable
from .timeline import timeline_frame_count


DEFAULT_FPS = 12.0
DEFAULT_FRAMES_PER_TRANSITION = 12


@dataclass(frozen=True)
class AnimationTiming:
    """Resolved timing values for rendered animation output."""

    frames_per_transition: int
    frame_count: int
    fps: float
    target_fps: float
    duration_seconds: float
    seconds_per_transition: float


def resolve_animation_timing(
    table: KeyframeTable,
    *,
    frames_per_transition: int | None = None,
    fps: float | None = None,
    total_duration_seconds: float | None = None,
    seconds_per_transition: float | None = None,
) -> AnimationTiming:
    """Resolve animation duration and playback frame rate.

    Without a duration option, `frames_per_transition` controls how many samples
    are rendered between adjacent keyframes. With a duration option, `fps` is
    treated as the target frame rate and `frames_per_transition` is calculated so
    each keyframe still appears exactly in the rendered sequence.
    """

    if total_duration_seconds is not None and seconds_per_transition is not None:
        raise KeyframeDataError(
            "Choose either total duration or seconds per transition, not both."
        )
    if table.frame_count < 2:
        raise KeyframeDataError("At least two keyframes are required.")

    transition_count = table.frame_count - 1
    target_fps = _positive_float(DEFAULT_FPS if fps is None else fps, "fps")

    if frames_per_transition is not None and (
        total_duration_seconds is not None or seconds_per_transition is not None
    ):
        raise KeyframeDataError(
            "Duration options calculate frames per transition; do not set both."
        )

    if total_duration_seconds is not None:
        duration_seconds = _positive_float(
            total_duration_seconds,
            "total_duration_seconds",
        )
        transition_seconds = duration_seconds / transition_count
    elif seconds_per_transition is not None:
        transition_seconds = _positive_float(
            seconds_per_transition,
            "seconds_per_transition",
        )
        duration_seconds = transition_count * transition_seconds
    else:
        resolved_frames_per_transition = _positive_int(
            DEFAULT_FRAMES_PER_TRANSITION
            if frames_per_transition is None
            else frames_per_transition,
            "frames_per_transition",
        )
        frame_count = timeline_frame_count(
            table,
            frames_per_transition=resolved_frames_per_transition,
        )
        resolved_fps = target_fps
        duration_seconds = frame_count / resolved_fps
        transition_seconds = duration_seconds / transition_count
        return AnimationTiming(
            frames_per_transition=resolved_frames_per_transition,
            frame_count=frame_count,
            fps=resolved_fps,
            target_fps=target_fps,
            duration_seconds=duration_seconds,
            seconds_per_transition=transition_seconds,
        )

    target_frame_count = duration_seconds * target_fps
    resolved_frames_per_transition = max(
        1,
        _round_half_up((target_frame_count - 1) / transition_count),
    )
    frame_count = timeline_frame_count(
        table,
        frames_per_transition=resolved_frames_per_transition,
    )
    resolved_fps = frame_count / duration_seconds

    return AnimationTiming(
        frames_per_transition=resolved_frames_per_transition,
        frame_count=frame_count,
        fps=resolved_fps,
        target_fps=target_fps,
        duration_seconds=duration_seconds,
        seconds_per_transition=transition_seconds,
    )


def _positive_float(value: float, name: str) -> float:
    resolved = float(value)
    if resolved <= 0:
        raise KeyframeDataError(f"{name} must be greater than zero.")
    return resolved


def _positive_int(value: int, name: str) -> int:
    resolved = int(value)
    if resolved <= 0:
        raise KeyframeDataError(f"{name} must be greater than zero.")
    return resolved


def _round_half_up(value: float) -> int:
    return int(floor(value + 0.5))
