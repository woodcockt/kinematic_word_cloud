"""Tools for animating word clouds from tabular keyframe data."""

import os
from pathlib import Path
from tempfile import gettempdir


_CACHE_ROOT = Path(gettempdir()) / "kinematic_word_cloud"
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT))

from .api import RenderOptions, RenderResult, render_animation, render_from_csv
from .config import (
    ASPECT_CHOICES,
    CanvasSize,
    AnimationTiming,
    resolve_animation_timing,
    resolve_canvas_size,
)
from .data import KeyframeDataError, KeyframeTable, load_keyframes
from .labels import LabelConfig
from .layout import ColorOptions
from .render_config import load_render_config
from .scenes import (
    ATTRACTORS_SCENE_POSITIONING,
    DEFAULT_LAYOUT_MODE,
    DEFAULT_SCENE_POSITIONING,
    DEFAULT_SCENE_SETTLE_STEPS,
    GLOBAL_LAYOUT_MODE,
    SCENE_LAYOUT_MODE,
    SCENE_POSITIONING_MODES,
    SETTLED_LINE_SCENE_POSITIONING,
    SETTLED_CENTER_SCENE_POSITIONING,
    SceneKeyframeData,
    SceneRenderInfo,
    SceneSlice,
    WORDCLOUD_SCENE_POSITIONING,
)

__all__ = [
    "AnimationTiming",
    "ASPECT_CHOICES",
    "ATTRACTORS_SCENE_POSITIONING",
    "CanvasSize",
    "KeyframeDataError",
    "KeyframeTable",
    "LabelConfig",
    "ColorOptions",
    "RenderOptions",
    "RenderResult",
    "SceneKeyframeData",
    "SceneRenderInfo",
    "SceneSlice",
    "DEFAULT_LAYOUT_MODE",
    "GLOBAL_LAYOUT_MODE",
    "SCENE_LAYOUT_MODE",
    "DEFAULT_SCENE_POSITIONING",
    "DEFAULT_SCENE_SETTLE_STEPS",
    "SCENE_POSITIONING_MODES",
    "SETTLED_CENTER_SCENE_POSITIONING",
    "SETTLED_LINE_SCENE_POSITIONING",
    "WORDCLOUD_SCENE_POSITIONING",
    "load_render_config",
    "load_keyframes",
    "render_animation",
    "render_from_csv",
    "resolve_animation_timing",
    "resolve_canvas_size",
]
