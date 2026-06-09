"""Scene-based layout support for sparse, long-form animations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import floor
from pathlib import Path

import pandas as pd

from .change_color import max_absolute_change
from .config import (
    AnimationTiming,
    DEFAULT_CANVAS_SIZE,
    DEFAULT_FPS,
    DEFAULT_FRAMES_PER_TRANSITION,
)
from .data import (
    DEFAULT_COLOR_COLUMN,
    DEFAULT_GROUP_COLUMN,
    DEFAULT_WORD_COLUMN,
    KeyframeDataError,
    KeyframeTable,
    _clean_column_name,
    _clean_optional_text,
    _clean_word,
    _validate_unique,
    from_wide_dataframe,
)
from .effects import BloomConfig
from .labels import LabelConfig, label_for_frame
from .layout import ABSOLUTECHANGE_COLOR_BY, ColorOptions, SCALEDCHANGE_COLOR_BY
from .physics import PhysicsConfig, PhysicsSimulator, WordBodySpec
from .render import (
    _build_size_reference_layout,
    _clear_animation_frames,
    _clamp_values_to_size_max,
    _layout_centers,
    _measure_peak_sizes,
    render_fixed_frame,
)
from .timeline import DEFAULT_INTERPOLATION, iter_timeline_frames


GLOBAL_LAYOUT_MODE = "global"
SCENE_LAYOUT_MODE = "scene"
LAYOUT_MODES: tuple[str, ...] = (GLOBAL_LAYOUT_MODE, SCENE_LAYOUT_MODE)
DEFAULT_LAYOUT_MODE = GLOBAL_LAYOUT_MODE
DEFAULT_SCENE_COLUMN = "scene"
DEFAULT_ID_COLUMN = "id"
DEFAULT_X_COLUMN = "x"
DEFAULT_Y_COLUMN = "y"


@dataclass(frozen=True)
class SceneSlice:
    """A normalized scene-specific keyframe table and its layout metadata."""

    name: str
    start_frame: str
    end_frame: str
    start_index: int
    end_index: int
    table: KeyframeTable
    ids_by_word: dict[str, str]
    positions_by_word: dict[str, tuple[float, float]]

    @property
    def frames(self) -> list[str]:
        """Frame labels covered by this scene."""

        return self.table.frames


@dataclass(frozen=True)
class SceneKeyframeData:
    """A scene-sliced keyframe input."""

    scenes: tuple[SceneSlice, ...]
    frames: list[str]
    source: Path | None = None

    @property
    def frame_count(self) -> int:
        """Number of global keyframe labels in the input."""

        return len(self.frames)

    @property
    def scene_count(self) -> int:
        """Number of configured scenes."""

        return len(self.scenes)

    @property
    def transition_count(self) -> int:
        """Number of interpolated transitions rendered across all scenes."""

        return sum(scene.table.frame_count - 1 for scene in self.scenes)

    def timeline_table(self) -> KeyframeTable:
        """Return a lightweight table over the global labels for result metadata."""

        values = pd.DataFrame(
            [[1.0 for _ in self.frames]],
            index=pd.Index(["__timeline__"], name=DEFAULT_WORD_COLUMN),
            columns=self.frames,
        )
        return KeyframeTable(values=values, source=self.source)


@dataclass(frozen=True)
class SceneRenderInfo:
    """Resolved render metadata for one scene."""

    name: str
    start_frame_index: int
    frame_count: int
    centers_by_id: dict[str, tuple[float, float]]
    peak_sizes_by_id: dict[str, tuple[int, int]]


def load_scene_keyframes(
    path: str | Path,
    *,
    scene_starts: Mapping[str, str],
    word_column: str = DEFAULT_WORD_COLUMN,
    scene_column: str = DEFAULT_SCENE_COLUMN,
    id_column: str = DEFAULT_ID_COLUMN,
    color_column: str = DEFAULT_COLOR_COLUMN,
    group_column: str = DEFAULT_GROUP_COLUMN,
    x_column: str = DEFAULT_X_COLUMN,
    y_column: str = DEFAULT_Y_COLUMN,
) -> SceneKeyframeData:
    """Load a wide scene keyframe table from disk."""

    source = Path(path)
    if source.suffix.lower() != ".csv":
        raise KeyframeDataError(f"Expected a CSV file, got: {source}")

    try:
        dataframe = pd.read_csv(source)
    except FileNotFoundError as exc:
        raise KeyframeDataError(f"Keyframe CSV not found: {source}") from exc
    except pd.errors.EmptyDataError as exc:
        raise KeyframeDataError(f"Keyframe CSV is empty: {source}") from exc

    return from_scene_dataframe(
        dataframe,
        scene_starts=scene_starts,
        word_column=word_column,
        scene_column=scene_column,
        id_column=id_column,
        color_column=color_column,
        group_column=group_column,
        x_column=x_column,
        y_column=y_column,
        source=source,
    )


def from_scene_dataframe(
    dataframe: pd.DataFrame,
    *,
    scene_starts: Mapping[str, str],
    word_column: str = DEFAULT_WORD_COLUMN,
    scene_column: str = DEFAULT_SCENE_COLUMN,
    id_column: str = DEFAULT_ID_COLUMN,
    color_column: str = DEFAULT_COLOR_COLUMN,
    group_column: str = DEFAULT_GROUP_COLUMN,
    x_column: str = DEFAULT_X_COLUMN,
    y_column: str = DEFAULT_Y_COLUMN,
    source: str | Path | None = None,
) -> SceneKeyframeData:
    """Normalize a single wide CSV into per-scene keyframe tables."""

    if dataframe.empty:
        raise KeyframeDataError("Scene keyframe table must contain at least one row.")

    starts = _normalize_scene_starts(scene_starts)
    normalized = dataframe.copy()
    normalized.columns = [_clean_column_name(column) for column in normalized.columns]
    word_column = _clean_column_name(word_column)
    scene_column = _clean_column_name(scene_column)
    id_column = _clean_column_name(id_column)
    color_column = _clean_column_name(color_column)
    group_column = _clean_column_name(group_column)
    x_column = _clean_column_name(x_column)
    y_column = _clean_column_name(y_column)

    for required_column in (scene_column, word_column):
        if required_column not in normalized.columns:
            raise KeyframeDataError(
                f"Missing required scene column: {required_column!r}"
            )

    metadata_columns = {
        scene_column,
        word_column,
        id_column,
        color_column,
        group_column,
        x_column,
        y_column,
    }
    frame_columns = [
        column for column in normalized.columns if column not in metadata_columns
    ]
    if len(frame_columns) < 2:
        raise KeyframeDataError(
            "Scene keyframe table must contain at least two frame columns."
        )
    _validate_unique(frame_columns, label="frame column")
    scene_ranges = _scene_ranges(starts, frame_columns)

    scenes = normalized[scene_column].map(_clean_optional_text)
    if scenes.isna().any():
        raise KeyframeDataError("Scene column contains blank or missing values.")
    unknown_scenes = sorted(set(scenes) - set(starts))
    if unknown_scenes:
        raise KeyframeDataError(
            "CSV scene names must exist in scene_starts. Unknown scenes: "
            + ", ".join(unknown_scenes)
        )

    words = normalized[word_column].map(_clean_word)
    if words.isna().any():
        raise KeyframeDataError("Word column contains blank or missing values.")
    ids = _read_ids(normalized, words, id_column)
    positions = _read_positions(normalized, words, x_column, y_column)
    values = normalized.loc[:, frame_columns].apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any():
        bad_columns = values.columns[values.isna().any()].tolist()
        raise KeyframeDataError(
            "Frame values must be numeric. Invalid values found in: "
            + ", ".join(map(str, bad_columns))
        )
    if (values < 0).any().any():
        raise KeyframeDataError("Frame values must be non-negative.")
    normalized.loc[:, frame_columns] = values

    scene_slices: list[SceneSlice] = []
    for scene_name, start_index, end_index in scene_ranges:
        scene_mask = scenes == scene_name
        if not bool(scene_mask.any()):
            raise KeyframeDataError(f"Scene {scene_name!r} has no CSV rows.")
        scene_frame_columns = frame_columns[start_index : end_index + 1]
        if len(scene_frame_columns) < 2:
            raise KeyframeDataError(
                f"Scene {scene_name!r} must cover at least two frame labels."
            )

        scene_words = words.loc[scene_mask].tolist()
        scene_ids = ids.loc[scene_mask].tolist()
        _validate_unique(scene_ids, label=f"id in scene {scene_name!r}")

        scene_dataframe = normalized.loc[
            scene_mask,
            [
                column
                for column in (
                    word_column,
                    color_column,
                    group_column,
                    *scene_frame_columns,
                )
                if column in normalized.columns
            ],
        ].copy()
        table = from_wide_dataframe(
            scene_dataframe,
            word_column=word_column,
            color_column=color_column,
            group_column=group_column,
            source=source,
        )
        ids_by_word = {
            str(word): str(row_id)
            for word, row_id in zip(scene_words, scene_ids, strict=True)
        }
        positions_by_word = {
            str(word): position
            for word, position in zip(
                scene_words,
                positions.loc[scene_mask].tolist(),
                strict=True,
            )
            if position is not None
        }
        scene_slices.append(
            SceneSlice(
                name=scene_name,
                start_frame=scene_frame_columns[0],
                end_frame=scene_frame_columns[-1],
                start_index=start_index,
                end_index=end_index,
                table=table,
                ids_by_word=ids_by_word,
                positions_by_word=positions_by_word,
            )
        )

    return SceneKeyframeData(
        scenes=tuple(scene_slices),
        frames=list(frame_columns),
        source=Path(source) if source is not None else None,
    )


def resolve_scene_animation_timing(
    scene_data: SceneKeyframeData,
    *,
    frames_per_transition: int | None = None,
    fps: float | None = None,
    total_duration_seconds: float | None = None,
    seconds_per_transition: float | None = None,
) -> AnimationTiming:
    """Resolve timing for separately rendered scene spans."""

    if total_duration_seconds is not None and seconds_per_transition is not None:
        raise KeyframeDataError(
            "Choose either total duration or seconds per transition, not both."
        )
    transition_count = scene_data.transition_count
    if transition_count < 1:
        raise KeyframeDataError("At least one scene transition is required.")

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
        frame_count = _scene_frame_count(
            scene_data,
            frames_per_transition=resolved_frames_per_transition,
        )
        duration_seconds = frame_count / target_fps
        return AnimationTiming(
            frames_per_transition=resolved_frames_per_transition,
            frame_count=frame_count,
            fps=target_fps,
            target_fps=target_fps,
            duration_seconds=duration_seconds,
            seconds_per_transition=duration_seconds / transition_count,
        )

    target_frame_count = duration_seconds * target_fps
    resolved_frames_per_transition = max(
        1,
        _round_half_up(
            (target_frame_count - scene_data.scene_count) / transition_count
        ),
    )
    frame_count = _scene_frame_count(
        scene_data,
        frames_per_transition=resolved_frames_per_transition,
    )
    resolved_fps = frame_count / duration_seconds
    return AnimationTiming(
        frames_per_transition=resolved_frames_per_transition,
        frame_count=frame_count,
        fps=resolved_fps,
        target_fps=target_fps,
        duration_seconds=duration_seconds,
        seconds_per_transition=duration_seconds / transition_count,
    )


def render_scene_animation_frames(
    scene_data: SceneKeyframeData,
    output_dir: str | Path,
    *,
    frames_per_transition: int = 12,
    width: int = DEFAULT_CANVAS_SIZE.width,
    height: int = DEFAULT_CANVAS_SIZE.height,
    background_color: str = "white",
    random_state: int = 42,
    colormap: str = "viridis",
    min_font_size: int = 4,
    use_physics: bool = False,
    physics_config: PhysicsConfig | None = None,
    label_config: LabelConfig | None = None,
    interpolation: str = DEFAULT_INTERPOLATION,
    color_options: ColorOptions | None = None,
    bloom_config: BloomConfig | None = None,
    size_max_value: float | None = None,
) -> tuple[list[Path], tuple[SceneRenderInfo, ...]]:
    """Render one continuous raster frame sequence from per-scene layouts."""

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _clear_animation_frames(output)

    frame_paths: list[Path] = []
    scene_infos: list[SceneRenderInfo] = []
    carryover_centers_by_id: dict[str, tuple[float, float]] = {}
    color_by_absolutechange = (
        color_options is not None
        and color_options.color_by == ABSOLUTECHANGE_COLOR_BY
    )
    color_by_scaledchange = (
        color_options is not None
        and color_options.color_by == SCALEDCHANGE_COLOR_BY
    )
    uses_transition_colors = color_by_absolutechange or color_by_scaledchange
    scaledchange_max_absolute_change = (
        max_absolute_change(
            scene.table.frame_values(frame)
            for scene in scene_data.scenes
            for frame in scene.table.frames
        )
        if color_by_scaledchange
        else 0.0
    )

    for scene in scene_data.scenes:
        layout, size_reference_values = _build_size_reference_layout(
            scene.table,
            width=width,
            height=height,
            background_color=background_color,
            random_state=random_state,
            colormap=colormap,
            color_options=color_options,
            size_max_value=size_max_value,
        )
        font_path = getattr(layout.wordcloud, "font_path")
        peak_sizes = _measure_peak_sizes(layout, font_path=font_path)
        default_centers = _layout_centers(layout, peak_sizes)
        resolved_centers = _resolve_scene_centers(
            scene,
            default_centers=default_centers,
            carryover_centers_by_id=carryover_centers_by_id,
            width=width,
            height=height,
        )
        simulator = (
            _build_scene_physics_simulator(
                scene,
                layout=layout,
                peak_sizes=peak_sizes,
                centers=resolved_centers,
                canvas_size=(width, height),
                config=physics_config,
            )
            if use_physics
            else None
        )
        scene_start_frame_index = len(frame_paths)
        last_centers = resolved_centers

        for frame in iter_timeline_frames(
            scene.table,
            frames_per_transition=frames_per_transition,
            interpolation=interpolation,
        ):
            frame_path = output / f"frame_{len(frame_paths):04d}.png"
            physics_values = _clamp_values_to_size_max(
                frame.values,
                size_max_value,
            )
            centers = (
                simulator.step(physics_values, size_reference_values)
                if simulator is not None
                else resolved_centers
            )
            last_centers = centers
            change_start_values = (
                scene.table.frame_values(frame.start_keyframe)
                if uses_transition_colors
                else None
            )
            change_end_values = (
                scene.table.frame_values(frame.end_keyframe)
                if uses_transition_colors
                else None
            )
            render_fixed_frame(
                scene.table,
                layout,
                frame.values,
                frame_path,
                background_color=background_color,
                min_font_size=min_font_size,
                centers=centers,
                label_text=label_for_frame(frame, label_config),
                label_config=label_config,
                bloom_config=bloom_config,
                change_start_values=change_start_values,
                change_end_values=change_end_values,
                color_options=color_options,
                scaledchange_max_absolute_change=scaledchange_max_absolute_change,
                size_reference_values=size_reference_values,
                size_max_value=size_max_value,
            )
            frame_paths.append(frame_path)

        centers_by_id = {
            scene.ids_by_word[word]: last_centers.get(word, resolved_centers[word])
            for word in scene.table.words
        }
        peak_sizes_by_id = {
            scene.ids_by_word[word]: peak_sizes[word]
            for word in scene.table.words
        }
        carryover_centers_by_id.update(centers_by_id)
        scene_infos.append(
            SceneRenderInfo(
                name=scene.name,
                start_frame_index=scene_start_frame_index,
                frame_count=len(frame_paths) - scene_start_frame_index,
                centers_by_id=centers_by_id,
                peak_sizes_by_id=peak_sizes_by_id,
            )
        )

    return frame_paths, tuple(scene_infos)


def _normalize_scene_starts(scene_starts: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(scene_starts, Mapping) or not scene_starts:
        raise KeyframeDataError("scene_starts must define at least one scene.")

    starts: dict[str, str] = {}
    for raw_scene, raw_frame in scene_starts.items():
        scene = _clean_optional_text(raw_scene)
        frame = _clean_optional_text(raw_frame)
        if scene is None or frame is None:
            raise KeyframeDataError("scene_starts cannot contain blank values.")
        if scene in starts:
            raise KeyframeDataError(f"Duplicate scene in scene_starts: {scene!r}")
        starts[scene] = frame
    _validate_unique(list(starts.values()), label="scene start frame")
    return starts


def _scene_ranges(
    scene_starts: Mapping[str, str],
    frame_columns: list[str],
) -> list[tuple[str, int, int]]:
    frame_indexes = {frame: index for index, frame in enumerate(frame_columns)}
    for scene_name, start_frame in scene_starts.items():
        if start_frame not in frame_indexes:
            raise KeyframeDataError(
                f"Scene {scene_name!r} starts at unknown frame label: "
                f"{start_frame!r}"
            )

    ranges: list[tuple[str, int, int]] = []
    previous_start = -1
    entries = list(scene_starts.items())
    for index, (scene_name, start_frame) in enumerate(entries):
        start_index = frame_indexes[start_frame]
        if start_index <= previous_start:
            raise KeyframeDataError(
                "scene_starts must be listed in increasing frame order."
            )
        next_start_index = (
            frame_indexes[entries[index + 1][1]]
            if index + 1 < len(entries)
            else len(frame_columns)
        )
        end_index = next_start_index - 1
        ranges.append((scene_name, start_index, end_index))
        previous_start = start_index
    return ranges


def _read_ids(
    dataframe: pd.DataFrame,
    words: pd.Series,
    id_column: str,
) -> pd.Series:
    if id_column not in dataframe.columns:
        return words.astype(str)

    ids = dataframe[id_column].map(_clean_optional_text)
    return pd.Series(
        [
            str(row_id) if row_id is not None else str(word)
            for row_id, word in zip(ids, words, strict=True)
        ],
        index=dataframe.index,
    )


def _read_positions(
    dataframe: pd.DataFrame,
    words: pd.Series,
    x_column: str,
    y_column: str,
) -> pd.Series:
    has_x = x_column in dataframe.columns
    has_y = y_column in dataframe.columns
    if not has_x and not has_y:
        return pd.Series([None for _ in words], index=dataframe.index)
    if has_x != has_y:
        raise KeyframeDataError("Scene positions require both x and y columns.")

    positions: list[tuple[float, float] | None] = []
    for word, raw_x, raw_y in zip(
        words,
        dataframe[x_column],
        dataframe[y_column],
        strict=True,
    ):
        x_text = _clean_optional_text(raw_x)
        y_text = _clean_optional_text(raw_y)
        if x_text is None and y_text is None:
            positions.append(None)
            continue
        if x_text is None or y_text is None:
            raise KeyframeDataError(
                f"Scene position for word {word!r} requires both x and y."
            )
        try:
            x = float(x_text)
            y = float(y_text)
        except ValueError as exc:
            raise KeyframeDataError(
                f"Scene position for word {word!r} must be numeric."
            ) from exc
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise KeyframeDataError(
                f"Scene position for word {word!r} must be between 0 and 1."
            )
        positions.append((x, y))
    return pd.Series(positions, index=dataframe.index)


def _resolve_scene_centers(
    scene: SceneSlice,
    *,
    default_centers: Mapping[str, tuple[float, float]],
    carryover_centers_by_id: Mapping[str, tuple[float, float]],
    width: int,
    height: int,
) -> dict[str, tuple[float, float]]:
    centers: dict[str, tuple[float, float]] = {}
    for word in scene.table.words:
        row_id = scene.ids_by_word[word]
        if word in scene.positions_by_word:
            x, y = scene.positions_by_word[word]
            centers[word] = (x * width, y * height)
        elif row_id in carryover_centers_by_id:
            centers[word] = carryover_centers_by_id[row_id]
        else:
            centers[word] = default_centers[word]
    return centers


def _build_scene_physics_simulator(
    scene: SceneSlice,
    *,
    layout,
    peak_sizes: Mapping[str, tuple[int, int]],
    centers: Mapping[str, tuple[float, float]],
    canvas_size: tuple[int, int],
    config: PhysicsConfig | None,
) -> PhysicsSimulator:
    specs = [
        WordBodySpec(
            word=word_layout.word,
            anchor=centers[word_layout.word],
            peak_size=peak_sizes[word_layout.word],
        )
        for word_layout in layout.words
        if word_layout.word in scene.ids_by_word
    ]
    return PhysicsSimulator(specs, canvas_size=canvas_size, config=config)


def _scene_frame_count(
    scene_data: SceneKeyframeData,
    *,
    frames_per_transition: int,
) -> int:
    return sum(
        (scene.table.frame_count - 1) * frames_per_transition + 1
        for scene in scene_data.scenes
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
