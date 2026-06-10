"""Scene-based layout support for sparse, long-form animations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import cos, floor, pi, sin
from pathlib import Path

import pandas as pd
from PIL import Image

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
    ImageFrameItem,
    _build_size_reference_layout,
    _clear_animation_frames,
    _clamp_values_to_size_max,
    _layout_centers,
    _measure_peak_sizes,
    render_fixed_frame,
)
from .timeline import DEFAULT_INTERPOLATION, interpolate_values, iter_timeline_frames


GLOBAL_LAYOUT_MODE = "global"
SCENE_LAYOUT_MODE = "scene"
LAYOUT_MODES: tuple[str, ...] = (GLOBAL_LAYOUT_MODE, SCENE_LAYOUT_MODE)
DEFAULT_LAYOUT_MODE = GLOBAL_LAYOUT_MODE
DEFAULT_SCENE_COLUMN = "scene"
DEFAULT_ID_COLUMN = "id"
DEFAULT_X_COLUMN = "x"
DEFAULT_Y_COLUMN = "y"
DEFAULT_TYPE_COLUMN = "type"
DEFAULT_ASSET_COLUMN = "asset"
DEFAULT_ASSET_SCALE_COLUMN = "asset_scale"
DEFAULT_LAYER_COLUMN = "layer"
TEXT_ITEM_TYPE = "text"
IMAGE_ITEM_TYPE = "image"
ITEM_TYPES: tuple[str, ...] = (TEXT_ITEM_TYPE, IMAGE_ITEM_TYPE)
FRONT_IMAGE_LAYER = "front"
BACK_IMAGE_LAYER = "back"
IMAGE_LAYERS: tuple[str, ...] = (FRONT_IMAGE_LAYER, BACK_IMAGE_LAYER)
RASTER_IMAGE_SUFFIXES: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp")
WORDCLOUD_SCENE_POSITIONING = "wordcloud"
SETTLED_CENTER_SCENE_POSITIONING = "settled-center"
SETTLED_LINE_SCENE_POSITIONING = "settled-line"
SCENE_POSITIONING_MODES: tuple[str, ...] = (
    WORDCLOUD_SCENE_POSITIONING,
    SETTLED_CENTER_SCENE_POSITIONING,
    SETTLED_LINE_SCENE_POSITIONING,
)
DEFAULT_SCENE_POSITIONING = WORDCLOUD_SCENE_POSITIONING
DEFAULT_SCENE_SETTLE_STEPS = 120


@dataclass(frozen=True)
class SceneImageItem:
    """A static raster image item in one scene."""

    item_id: str
    asset_path: Path
    asset_scale: float
    layer: str = FRONT_IMAGE_LAYER
    position: tuple[float, float] | None = None


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
    image_values: pd.DataFrame
    image_items: tuple[SceneImageItem, ...] = ()

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
    type_column: str = DEFAULT_TYPE_COLUMN,
    asset_column: str = DEFAULT_ASSET_COLUMN,
    asset_scale_column: str = DEFAULT_ASSET_SCALE_COLUMN,
    layer_column: str = DEFAULT_LAYER_COLUMN,
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
        type_column=type_column,
        asset_column=asset_column,
        asset_scale_column=asset_scale_column,
        layer_column=layer_column,
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
    type_column: str = DEFAULT_TYPE_COLUMN,
    asset_column: str = DEFAULT_ASSET_COLUMN,
    asset_scale_column: str = DEFAULT_ASSET_SCALE_COLUMN,
    layer_column: str = DEFAULT_LAYER_COLUMN,
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
    type_column = _clean_column_name(type_column)
    asset_column = _clean_column_name(asset_column)
    asset_scale_column = _clean_column_name(asset_scale_column)
    layer_column = _clean_column_name(layer_column)

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
        type_column,
        asset_column,
        asset_scale_column,
        layer_column,
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

    item_types = _read_item_types(normalized, type_column)
    words = normalized[word_column].map(_clean_word)
    if words.loc[item_types == TEXT_ITEM_TYPE].isna().any():
        raise KeyframeDataError("Text rows must contain word values.")
    assets = _read_assets(
        normalized,
        item_types,
        words,
        asset_column,
        source=source,
    )
    ids = _read_ids(normalized, words, item_types, id_column)
    positions = _read_positions(normalized, ids, x_column, y_column)
    asset_scales = _read_asset_scales(normalized, item_types, asset_scale_column)
    image_layers = _read_image_layers(normalized, item_types, layer_column)
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

        scene_ids = ids.loc[scene_mask].tolist()
        _validate_unique(scene_ids, label=f"id in scene {scene_name!r}")
        text_mask = scene_mask & (item_types == TEXT_ITEM_TYPE)
        image_mask = scene_mask & (item_types == IMAGE_ITEM_TYPE)

        scene_dataframe = normalized.loc[
            text_mask,
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
        if scene_dataframe.empty:
            raise KeyframeDataError(
                f"Scene {scene_name!r} must contain at least one text row."
            )
        table = from_wide_dataframe(
            scene_dataframe,
            word_column=word_column,
            color_column=color_column,
            group_column=group_column,
            source=source,
        )
        ids_by_word = {
            str(word): str(row_id)
            for word, row_id in zip(
                words.loc[text_mask].tolist(),
                ids.loc[text_mask].tolist(),
                strict=True,
            )
        }
        positions_by_word = {
            str(word): position
            for word, position in zip(
                words.loc[text_mask].tolist(),
                positions.loc[text_mask].tolist(),
                strict=True,
            )
            if position is not None
        }
        image_values = values.loc[image_mask, scene_frame_columns].copy()
        image_values.index = ids.loc[image_mask].tolist()
        image_items = tuple(
            SceneImageItem(
                item_id=str(row_id),
                asset_path=asset,
                asset_scale=float(asset_scale),
                layer=str(layer),
                position=position,
            )
            for row_id, asset, asset_scale, layer, position in zip(
                ids.loc[image_mask].tolist(),
                assets.loc[image_mask].tolist(),
                asset_scales.loc[image_mask].tolist(),
                image_layers.loc[image_mask].tolist(),
                positions.loc[image_mask].tolist(),
                strict=True,
            )
            if asset is not None
        )
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
                image_values=image_values.astype(float),
                image_items=image_items,
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
    scene_positioning: str = DEFAULT_SCENE_POSITIONING,
    scene_settle_steps: int = DEFAULT_SCENE_SETTLE_STEPS,
) -> tuple[list[Path], tuple[SceneRenderInfo, ...]]:
    """Render one continuous raster frame sequence from per-scene layouts."""

    if scene_positioning not in SCENE_POSITIONING_MODES:
        raise KeyframeDataError(
            "scene_positioning must be one of: "
            + ", ".join(SCENE_POSITIONING_MODES)
        )
    if scene_settle_steps < 0:
        raise KeyframeDataError("scene_settle_steps must be non-negative.")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    _clear_animation_frames(output)

    frame_paths: list[Path] = []
    scene_infos: list[SceneRenderInfo] = []
    carryover_centers_by_id: dict[str, tuple[float, float]] = {}
    image_cache: dict[Path, Image.Image] = {}
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
        image_peak_values = _image_peak_values(scene, size_max_value)
        image_peak_sizes = _measure_image_peak_sizes(
            scene,
            image_cache=image_cache,
            canvas_size=(width, height),
        )
        resolved_image_centers = _resolve_scene_image_centers(
            scene,
            carryover_centers_by_id=carryover_centers_by_id,
            width=width,
            height=height,
        )
        text_anchor_centers = resolved_centers
        image_anchor_centers = resolved_image_centers
        text_initial_centers: Mapping[str, tuple[float, float]] | None = None
        image_initial_centers: Mapping[str, tuple[float, float]] | None = None
        settle_locked_ids: set[str] = set()
        if _uses_settled_scene_positioning(scene_positioning):
            text_anchor_centers, image_anchor_centers = _settled_scene_anchor_centers(
                scene,
                scene_positioning=scene_positioning,
                width=width,
                height=height,
            )
            text_initial_centers, image_initial_centers = (
                _settled_center_initial_centers(
                    scene,
                    resolved_centers=resolved_centers,
                    resolved_image_centers=resolved_image_centers,
                    carryover_centers_by_id=carryover_centers_by_id,
                    width=width,
                    height=height,
                )
            )
            settle_locked_ids = _scene_carryover_body_ids(
                scene,
                carryover_centers_by_id,
            )
        simulator = (
            _build_scene_physics_simulator(
                scene,
                layout=layout,
                peak_sizes=peak_sizes,
                centers=text_anchor_centers,
                initial_centers=text_initial_centers,
                image_peak_sizes=image_peak_sizes,
                image_centers=image_anchor_centers,
                initial_image_centers=image_initial_centers,
                canvas_size=(width, height),
                config=physics_config,
            )
            if use_physics or _uses_settled_scene_positioning(scene_positioning)
            else None
        )
        combined_peak_values = {
            **size_reference_values,
            **image_peak_values,
        }
        if (
            simulator is not None
            and _uses_settled_scene_positioning(scene_positioning)
            and scene_settle_steps > 0
        ):
            for _ in range(scene_settle_steps):
                simulator.step(
                    combined_peak_values,
                    combined_peak_values,
                    locked=settle_locked_ids,
                )
        scene_start_frame_index = len(frame_paths)
        last_centers = resolved_centers
        last_image_centers = resolved_image_centers

        for frame_index, frame in enumerate(
            iter_timeline_frames(
                scene.table,
                frames_per_transition=frames_per_transition,
                interpolation=interpolation,
            )
        ):
            frame_path = output / f"frame_{len(frame_paths):04d}.png"
            physics_values = _clamp_values_to_size_max(
                frame.values,
                size_max_value,
            )
            image_values = _frame_image_values(
                scene,
                frame.position,
                interpolation=interpolation,
            )
            image_physics_values = _clamp_values_to_size_max(
                image_values,
                size_max_value,
            )
            combined_physics_values = {
                **physics_values,
                **image_physics_values,
            }
            if (
                simulator is not None
                and _uses_settled_scene_positioning(scene_positioning)
                and frame_index == 0
            ):
                centers = simulator.centers()
            else:
                centers = (
                    simulator.step(combined_physics_values, combined_peak_values)
                    if simulator is not None
                    else resolved_centers
                )
            last_centers = centers
            image_centers = (
                {
                    image_item.item_id: centers[image_item.item_id]
                    for image_item in scene.image_items
                }
                if simulator is not None
                else resolved_image_centers
            )
            last_image_centers = image_centers
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
                image_items=_frame_image_items(
                    scene,
                    image_values=image_values,
                    image_peak_values=image_peak_values,
                    image_peak_sizes=image_peak_sizes,
                    image_centers=image_centers,
                    image_cache=image_cache,
                ),
            )
            frame_paths.append(frame_path)

        centers_by_id = {
            scene.ids_by_word[word]: last_centers.get(word, resolved_centers[word])
            for word in scene.table.words
        }
        centers_by_id.update(
            {
                image_item.item_id: last_image_centers.get(
                    image_item.item_id,
                    resolved_image_centers[image_item.item_id],
                )
                for image_item in scene.image_items
            }
        )
        peak_sizes_by_id = {
            scene.ids_by_word[word]: peak_sizes[word]
            for word in scene.table.words
        }
        peak_sizes_by_id.update(image_peak_sizes)
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


def _read_item_types(dataframe: pd.DataFrame, type_column: str) -> pd.Series:
    if type_column not in dataframe.columns:
        return pd.Series(
            [TEXT_ITEM_TYPE for _ in dataframe.index],
            index=dataframe.index,
        )

    item_types: list[str] = []
    for raw_type in dataframe[type_column]:
        item_type = _clean_optional_text(raw_type) or TEXT_ITEM_TYPE
        item_type = item_type.lower()
        if item_type not in ITEM_TYPES:
            raise KeyframeDataError(
                "Item type must be one of: " + ", ".join(ITEM_TYPES)
            )
        item_types.append(item_type)
    return pd.Series(item_types, index=dataframe.index)


def _read_assets(
    dataframe: pd.DataFrame,
    item_types: pd.Series,
    words: pd.Series,
    asset_column: str,
    *,
    source: str | Path | None,
) -> pd.Series:
    if asset_column not in dataframe.columns:
        if bool((item_types == IMAGE_ITEM_TYPE).any()):
            raise KeyframeDataError("Image rows require an asset column.")
        return pd.Series([None for _ in dataframe.index], index=dataframe.index)

    base_dir = _asset_base_dir(source)
    assets: list[Path | None] = []
    for item_type, word, raw_asset in zip(
        item_types,
        words,
        dataframe[asset_column],
        strict=True,
    ):
        asset_text = _clean_optional_text(raw_asset)
        if item_type == TEXT_ITEM_TYPE:
            assets.append(None)
            continue
        if asset_text is None:
            raise KeyframeDataError(f"Image item {word!r} requires an asset path.")

        asset_path = Path(asset_text)
        if not asset_path.is_absolute():
            asset_path = base_dir / asset_path
        if asset_path.suffix.lower() not in RASTER_IMAGE_SUFFIXES:
            raise KeyframeDataError(
                f"Unsupported image asset format for {asset_text!r}. "
                "Expected one of: " + ", ".join(RASTER_IMAGE_SUFFIXES)
            )
        if not asset_path.exists():
            raise KeyframeDataError(f"Image asset not found: {asset_path}")
        assets.append(asset_path)
    return pd.Series(assets, index=dataframe.index)


def _read_ids(
    dataframe: pd.DataFrame,
    words: pd.Series,
    item_types: pd.Series,
    id_column: str,
) -> pd.Series:
    raw_ids = (
        dataframe[id_column].map(_clean_optional_text)
        if id_column in dataframe.columns
        else pd.Series([None for _ in dataframe.index], index=dataframe.index)
    )

    ids: list[str] = []
    for raw_id, word, item_type in zip(
        raw_ids,
        words,
        item_types,
        strict=True,
    ):
        if raw_id is not None:
            ids.append(str(raw_id))
        elif item_type == IMAGE_ITEM_TYPE:
            raise KeyframeDataError("Image rows require explicit id values.")
        elif word is not None:
            ids.append(str(word))
        else:
            raise KeyframeDataError("Rows require id or word values.")

    return pd.Series(ids, index=dataframe.index)


def _read_asset_scales(
    dataframe: pd.DataFrame,
    item_types: pd.Series,
    asset_scale_column: str,
) -> pd.Series:
    if asset_scale_column not in dataframe.columns:
        return pd.Series([1.0 for _ in dataframe.index], index=dataframe.index)

    scales: list[float] = []
    for item_type, raw_scale in zip(
        item_types,
        dataframe[asset_scale_column],
        strict=True,
    ):
        if item_type == TEXT_ITEM_TYPE:
            scales.append(1.0)
            continue
        scale_text = _clean_optional_text(raw_scale)
        if scale_text is None:
            scales.append(1.0)
            continue
        try:
            scale = float(scale_text)
        except ValueError as exc:
            raise KeyframeDataError("asset_scale must be numeric.") from exc
        if scale <= 0:
            raise KeyframeDataError("asset_scale must be greater than zero.")
        scales.append(scale)

    return pd.Series(scales, index=dataframe.index)


def _read_image_layers(
    dataframe: pd.DataFrame,
    item_types: pd.Series,
    layer_column: str,
) -> pd.Series:
    if layer_column not in dataframe.columns:
        return pd.Series(
            [
                FRONT_IMAGE_LAYER if item_type == IMAGE_ITEM_TYPE else None
                for item_type in item_types
            ],
            index=dataframe.index,
        )

    layers: list[str | None] = []
    for item_type, raw_layer in zip(
        item_types,
        dataframe[layer_column],
        strict=True,
    ):
        if item_type == TEXT_ITEM_TYPE:
            layers.append(None)
            continue
        layer = (_clean_optional_text(raw_layer) or FRONT_IMAGE_LAYER).lower()
        if layer not in IMAGE_LAYERS:
            raise KeyframeDataError(
                "Image layer must be one of: " + ", ".join(IMAGE_LAYERS)
            )
        layers.append(layer)

    return pd.Series(layers, index=dataframe.index)


def _asset_base_dir(source: str | Path | None) -> Path:
    if source is None:
        return Path.cwd()
    return Path(source).parent


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


def _resolve_scene_image_centers(
    scene: SceneSlice,
    *,
    carryover_centers_by_id: Mapping[str, tuple[float, float]],
    width: int,
    height: int,
) -> dict[str, tuple[float, float]]:
    centers: dict[str, tuple[float, float]] = {}
    for image_item in scene.image_items:
        if image_item.position is not None:
            x, y = image_item.position
            centers[image_item.item_id] = (x * width, y * height)
        elif image_item.item_id in carryover_centers_by_id:
            centers[image_item.item_id] = carryover_centers_by_id[image_item.item_id]
        else:
            raise KeyframeDataError(
                f"Image item {image_item.item_id!r} requires x/y unless it "
                "inherits a position from an earlier scene."
            )
    return centers


def _image_peak_values(
    scene: SceneSlice,
    size_max_value: float | None,
) -> dict[str, float]:
    if scene.image_values.empty:
        return {}

    values = {
        str(item_id): float(value)
        for item_id, value in scene.image_values.max(axis=1).items()
    }
    if size_max_value is None:
        return values
    return {
        item_id: min(value, size_max_value) if value > 0 else 0.0
        for item_id, value in values.items()
    }


def _frame_image_values(
    scene: SceneSlice,
    position: float,
    *,
    interpolation: str,
) -> dict[str, float]:
    if scene.image_values.empty:
        return {}

    image_table = KeyframeTable(values=scene.image_values, source=scene.table.source)
    return interpolate_values(image_table, position, interpolation=interpolation)


def _measure_image_peak_sizes(
    scene: SceneSlice,
    *,
    image_cache: dict[Path, Image.Image],
    canvas_size: tuple[int, int],
) -> dict[str, tuple[int, int]]:
    sizes: dict[str, tuple[int, int]] = {}
    for image_item in scene.image_items:
        image = _load_image_asset(image_item.asset_path, image_cache=image_cache)
        sizes[image_item.item_id] = _responsive_image_peak_size(
            image,
            asset_scale=image_item.asset_scale,
            canvas_size=canvas_size,
        )
    return sizes


def _frame_image_items(
    scene: SceneSlice,
    *,
    image_values: Mapping[str, float],
    image_peak_values: Mapping[str, float],
    image_peak_sizes: Mapping[str, tuple[int, int]],
    image_centers: Mapping[str, tuple[float, float]],
    image_cache: dict[Path, Image.Image],
) -> tuple[ImageFrameItem, ...]:
    frame_items: list[ImageFrameItem] = []
    for image_item in scene.image_items:
        frame_items.append(
            ImageFrameItem(
                item_id=image_item.item_id,
                image=_load_image_asset(image_item.asset_path, image_cache=image_cache),
                center=image_centers[image_item.item_id],
                current_value=float(image_values.get(image_item.item_id, 0.0)),
                peak_value=float(image_peak_values.get(image_item.item_id, 0.0)),
                peak_size=image_peak_sizes[image_item.item_id],
                layer=image_item.layer,
            )
        )
    return tuple(frame_items)


def _responsive_image_peak_size(
    image: Image.Image,
    *,
    asset_scale: float,
    canvas_size: tuple[int, int],
) -> tuple[int, int]:
    canvas_width, canvas_height = canvas_size
    max_width = max(1.0, canvas_width * asset_scale)
    max_height = max(1.0, canvas_height * asset_scale)
    scale = min(max_width / image.width, max_height / image.height)
    width = max(1, int(round(image.width * scale)))
    height = max(1, int(round(image.height * scale)))
    return width, height


def _load_image_asset(
    path: Path,
    *,
    image_cache: dict[Path, Image.Image],
) -> Image.Image:
    if path not in image_cache:
        try:
            image_cache[path] = Image.open(path).convert("RGBA")
        except OSError as exc:
            raise KeyframeDataError(f"Could not load image asset: {path}") from exc
    return image_cache[path]


def _uses_settled_scene_positioning(scene_positioning: str) -> bool:
    return scene_positioning in {
        SETTLED_CENTER_SCENE_POSITIONING,
        SETTLED_LINE_SCENE_POSITIONING,
    }


def _settled_scene_anchor_centers(
    scene: SceneSlice,
    *,
    scene_positioning: str,
    width: int,
    height: int,
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, tuple[float, float]],
]:
    body_ids = [
        *scene.table.words,
        *(image_item.item_id for image_item in scene.image_items),
    ]
    if scene_positioning == SETTLED_CENTER_SCENE_POSITIONING:
        anchor_points = [
            (width / 2.0, height / 2.0)
            for _ in body_ids
        ]
    elif scene_positioning == SETTLED_LINE_SCENE_POSITIONING:
        anchor_points = _line_anchor_points(
            len(body_ids),
            width=width,
            height=height,
        )
    else:
        raise KeyframeDataError(
            "scene_positioning must be one of: "
            + ", ".join(SCENE_POSITIONING_MODES)
        )

    text_anchor_count = len(scene.table.words)
    text_anchors = {
        word: anchor
        for word, anchor in zip(
            scene.table.words,
            anchor_points[:text_anchor_count],
            strict=True,
        )
    }
    image_anchors = {
        image_item.item_id: anchor
        for image_item, anchor in zip(
            scene.image_items,
            anchor_points[text_anchor_count:],
            strict=True,
        )
    }
    return text_anchors, image_anchors


def _line_anchor_points(
    count: int,
    *,
    width: int,
    height: int,
) -> list[tuple[float, float]]:
    if count <= 0:
        return []
    if count == 1 or width == height:
        return [(width / 2.0, height / 2.0) for _ in range(count)]

    points: list[tuple[float, float]] = []
    if width > height:
        start_x = height / 2.0
        end_x = width - height / 2.0
        y = height / 2.0
        for index in range(count):
            position = (index + 1) / (count + 1)
            points.append((start_x + (end_x - start_x) * position, y))
    else:
        x = width / 2.0
        start_y = width / 2.0
        end_y = height - width / 2.0
        for index in range(count):
            position = (index + 1) / (count + 1)
            points.append((x, start_y + (end_y - start_y) * position))
    return points


def _settled_center_initial_centers(
    scene: SceneSlice,
    *,
    resolved_centers: Mapping[str, tuple[float, float]],
    resolved_image_centers: Mapping[str, tuple[float, float]],
    carryover_centers_by_id: Mapping[str, tuple[float, float]],
    width: int,
    height: int,
) -> tuple[
    dict[str, tuple[float, float]],
    dict[str, tuple[float, float]],
]:
    ring_points = _ring_spawn_points(
        len(scene.table.words) + len(scene.image_items),
        width=width,
        height=height,
    )
    ring_index = 0
    text_centers: dict[str, tuple[float, float]] = {}
    image_centers: dict[str, tuple[float, float]] = {}

    for word in scene.table.words:
        row_id = scene.ids_by_word[word]
        if row_id in carryover_centers_by_id:
            text_centers[word] = carryover_centers_by_id[row_id]
        elif word in scene.positions_by_word:
            text_centers[word] = resolved_centers[word]
        else:
            text_centers[word] = ring_points[ring_index]
            ring_index += 1

    for image_item in scene.image_items:
        if image_item.item_id in carryover_centers_by_id:
            image_centers[image_item.item_id] = carryover_centers_by_id[
                image_item.item_id
            ]
        elif image_item.position is not None:
            image_centers[image_item.item_id] = resolved_image_centers[
                image_item.item_id
            ]
        else:
            image_centers[image_item.item_id] = ring_points[ring_index]
            ring_index += 1

    return text_centers, image_centers


def _scene_carryover_body_ids(
    scene: SceneSlice,
    carryover_centers_by_id: Mapping[str, tuple[float, float]],
) -> set[str]:
    body_ids = {
        word
        for word in scene.table.words
        if scene.ids_by_word[word] in carryover_centers_by_id
    }
    body_ids.update(
        image_item.item_id
        for image_item in scene.image_items
        if image_item.item_id in carryover_centers_by_id
    )
    return body_ids


def _ring_spawn_points(
    count: int,
    *,
    width: int,
    height: int,
) -> list[tuple[float, float]]:
    if count <= 0:
        return []

    center_x = width / 2.0
    center_y = height / 2.0
    radius = min(width, height) * 0.45
    return [
        (
            center_x + cos((-pi / 2.0) + (2.0 * pi * index / count)) * radius,
            center_y + sin((-pi / 2.0) + (2.0 * pi * index / count)) * radius,
        )
        for index in range(count)
    ]


def _build_scene_physics_simulator(
    scene: SceneSlice,
    *,
    layout,
    peak_sizes: Mapping[str, tuple[int, int]],
    centers: Mapping[str, tuple[float, float]],
    initial_centers: Mapping[str, tuple[float, float]] | None = None,
    image_peak_sizes: Mapping[str, tuple[int, int]],
    image_centers: Mapping[str, tuple[float, float]],
    initial_image_centers: Mapping[str, tuple[float, float]] | None = None,
    canvas_size: tuple[int, int],
    config: PhysicsConfig | None,
) -> PhysicsSimulator:
    specs = [
        WordBodySpec(
            word=word_layout.word,
            anchor=centers[word_layout.word],
            peak_size=peak_sizes[word_layout.word],
            initial_position=(
                initial_centers.get(word_layout.word)
                if initial_centers is not None
                else None
            ),
        )
        for word_layout in layout.words
        if word_layout.word in scene.ids_by_word
    ]
    specs.extend(
        WordBodySpec(
            word=image_item.item_id,
            anchor=image_centers[image_item.item_id],
            peak_size=image_peak_sizes[image_item.item_id],
            initial_position=(
                initial_image_centers.get(image_item.item_id)
                if initial_image_centers is not None
                else None
            ),
        )
        for image_item in scene.image_items
    )
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
