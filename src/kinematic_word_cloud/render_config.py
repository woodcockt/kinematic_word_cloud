"""Render configuration loading and CLI override helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from PIL import ImageColor

from .data import HEX_COLOR_PATTERN, KeyframeDataError
from .effects import BLOOM_INTENSITY_MODES, BLOOM_SOURCES, BloomConfig
from .labels import LABEL_MODES, LABEL_POSITIONS, LabelConfig
from .layout import (
    COLOR_BY_MODES,
    COLOR_PALETTES,
    DEFAULT_COLOR_BY,
    DEFAULT_FALLBACK_COLOR,
    DEFAULT_PALETTE_NAME,
    ColorOptions,
)
from .timeline import DEFAULT_INTERPOLATION, INTERPOLATION_MODES


CONFIG_SUFFIX = ".toml"
EXPORT_FORMATS = ("gif", "mp4", "svg")


def load_render_config(path: str | Path | None) -> dict[str, Any]:
    """Load a render configuration from TOML."""

    if path is None:
        return {}

    config_path = Path(path)
    suffix = config_path.suffix.lower()
    if suffix == ".toml":
        config = _load_toml(config_path)
    else:
        raise KeyframeDataError("Config file must be TOML with a .toml suffix.")

    if not isinstance(config, dict):
        raise KeyframeDataError("Config file must contain an object/table.")

    return config


def setting(
    cli_values: object,
    config: Mapping[str, Any],
    key: str,
    default: Any,
) -> Any:
    """Resolve a setting with CLI values taking precedence over config values."""

    if hasattr(cli_values, key):
        return getattr(cli_values, key)
    if key in config:
        return config[key]

    aliases = {
        "total_duration": ("total_duration_seconds", "duration"),
        "seconds_per_transition": ("transition_duration",),
        "frames_per_transition": ("frame_samples",),
    }
    for alias in aliases.get(key, ()):
        if alias in config:
            return config[alias]

    label_config = config.get("label")
    if key.startswith("label_") and isinstance(label_config, Mapping):
        label_key = key.removeprefix("label_")
        label_aliases = {
            "mode": ("mode",),
            "position": ("position",),
            "size": ("size", "font_size"),
            "color": ("color",),
            "opacity": ("opacity",),
            "margin": ("margin",),
        }
        for alias in label_aliases.get(label_key, (label_key,)):
            if alias in label_config:
                return label_config[alias]

    absolutechange_config = config.get("absolutechange")
    if key.startswith("absolutechange_") and isinstance(
        absolutechange_config,
        Mapping,
    ):
        absolutechange_key = key.removeprefix("absolutechange_")
        absolutechange_aliases = {
            "growth_color": ("growth_color", "growth"),
            "decline_color": ("decline_color", "decline", "reduction"),
            "no_change_color": ("no_change_color", "no_change", "neutral"),
        }
        for alias in absolutechange_aliases.get(
            absolutechange_key,
            (absolutechange_key,),
        ):
            if alias in absolutechange_config:
                return absolutechange_config[alias]

    scaledchange_config = config.get("scaledchange")
    if key.startswith("scaledchange_") and isinstance(
        scaledchange_config,
        Mapping,
    ):
        scaledchange_key = key.removeprefix("scaledchange_")
        scaledchange_aliases = {
            "colors": ("colors", "palette"),
        }
        for alias in scaledchange_aliases.get(
            scaledchange_key,
            (scaledchange_key,),
        ):
            if alias in scaledchange_config:
                return scaledchange_config[alias]

    return default


def resolve_timing_values(
    cli_values: object,
    config: Mapping[str, Any],
) -> dict[str, float | int | None]:
    """Resolve timing values, allowing CLI timing choices to replace config."""

    cli_sets_frames = hasattr(cli_values, "frames_per_transition")
    cli_sets_total_duration = hasattr(cli_values, "total_duration")
    cli_sets_transition_duration = hasattr(cli_values, "seconds_per_transition")
    cli_sets_duration = cli_sets_total_duration or cli_sets_transition_duration

    frames_per_transition = optional_int(
        setting(cli_values, config, "frames_per_transition", None),
        "frames_per_transition",
    )
    total_duration = optional_float(
        setting(cli_values, config, "total_duration", None),
        "total_duration",
    )
    seconds_per_transition = optional_float(
        setting(cli_values, config, "seconds_per_transition", None),
        "seconds_per_transition",
    )

    if cli_sets_frames and not cli_sets_duration:
        total_duration = None
        seconds_per_transition = None
    if cli_sets_duration and not cli_sets_frames:
        frames_per_transition = None
    if cli_sets_total_duration and not cli_sets_transition_duration:
        seconds_per_transition = None
    if cli_sets_transition_duration and not cli_sets_total_duration:
        total_duration = None

    return {
        "frames_per_transition": frames_per_transition,
        "fps": optional_float(setting(cli_values, config, "fps", None), "fps"),
        "total_duration": total_duration,
        "seconds_per_transition": seconds_per_transition,
    }


def build_label_config(
    cli_values: object,
    config: Mapping[str, Any],
) -> LabelConfig | None:
    """Resolve label overlay configuration."""

    mode = str(setting(cli_values, config, "label_mode", "none"))
    if mode == "none":
        return None
    if mode not in LABEL_MODES:
        raise KeyframeDataError(
            "label_mode must be one of: " + ", ".join(map(str, LABEL_MODES))
        )

    position = str(setting(cli_values, config, "label_position", "top-left"))
    if position not in LABEL_POSITIONS:
        raise KeyframeDataError(
            "label_position must be one of: "
            + ", ".join(map(str, LABEL_POSITIONS))
        )

    label_size = optional_int(setting(cli_values, config, "label_size", 56), "label_size")
    label_margin = optional_int(
        setting(cli_values, config, "label_margin", 32),
        "label_margin",
    )
    label_opacity = optional_float(
        setting(cli_values, config, "label_opacity", 0.85),
        "label_opacity",
    )
    if label_size is None or label_size <= 0:
        raise KeyframeDataError("label_size must be greater than zero.")
    if label_margin is None or label_margin < 0:
        raise KeyframeDataError("label_margin must be non-negative.")
    if label_opacity is None or not 0 <= label_opacity <= 1:
        raise KeyframeDataError("label_opacity must be between 0 and 1.")

    return LabelConfig(
        mode=mode,
        position=position,
        font_size=label_size,
        color=str(setting(cli_values, config, "label_color", "#222222")),
        opacity=label_opacity,
        margin=label_margin,
    )


def resolve_interpolation(
    cli_values: object,
    config: Mapping[str, Any],
) -> str:
    """Resolve the timeline interpolation mode."""

    interpolation = str(
        setting(cli_values, config, "interpolation", DEFAULT_INTERPOLATION)
    )
    if interpolation not in INTERPOLATION_MODES:
        raise KeyframeDataError(
            "interpolation must be one of: " + ", ".join(INTERPOLATION_MODES)
        )
    return interpolation


def resolve_color_options(
    cli_values: object,
    config: Mapping[str, Any],
    *,
    project_root: Path,
) -> ColorOptions:
    """Resolve word color assignment options."""

    palette = _resolve_palette(cli_values, config, project_root=project_root)

    color_by = str(setting(cli_values, config, "color_by", DEFAULT_COLOR_BY))
    if color_by not in COLOR_BY_MODES:
        raise KeyframeDataError(
            "color_by must be one of: " + ", ".join(COLOR_BY_MODES)
        )

    color_defaults = ColorOptions()
    default_color = _normalize_hex_color(
        setting(cli_values, config, "default_color", DEFAULT_FALLBACK_COLOR),
        "default_color",
    )
    absolutechange_growth_color = _normalize_hex_color(
        setting(
            cli_values,
            config,
            "absolutechange_growth_color",
            color_defaults.absolutechange_growth_color,
        ),
        "absolutechange_growth_color",
    )
    absolutechange_decline_color = _normalize_hex_color(
        setting(
            cli_values,
            config,
            "absolutechange_decline_color",
            color_defaults.absolutechange_decline_color,
        ),
        "absolutechange_decline_color",
    )
    absolutechange_no_change_color = _normalize_hex_color(
        setting(
            cli_values,
            config,
            "absolutechange_no_change_color",
            color_defaults.absolutechange_no_change_color,
        ),
        "absolutechange_no_change_color",
    )
    scaledchange_colors = _parse_color_stops(
        setting(
            cli_values,
            config,
            "scaledchange_colors",
            color_defaults.scaledchange_colors,
        ),
        "scaledchange_colors",
    )
    group_colors = _parse_config_group_colors(config.get("group_colors", {}))
    if hasattr(cli_values, "group_color"):
        group_colors.update(_parse_cli_group_colors(getattr(cli_values, "group_color")))

    return ColorOptions(
        palette=palette,
        color_by=color_by,
        group_colors=group_colors,
        default_color=default_color,
        absolutechange_growth_color=absolutechange_growth_color,
        absolutechange_decline_color=absolutechange_decline_color,
        absolutechange_no_change_color=absolutechange_no_change_color,
        scaledchange_colors=scaledchange_colors,
    )


def build_bloom_config(
    cli_values: object,
    config: Mapping[str, Any],
) -> BloomConfig | None:
    """Resolve optional raster bloom configuration."""

    bloom_table = _bloom_table(config)
    enabled = optional_bool(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom",
            table_key="enabled",
            top_level_key="bloom",
            default=False,
        ),
        "bloom",
    )
    if not enabled:
        return None

    defaults = BloomConfig()
    radius_scale = optional_float(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_radius_scale",
            table_key="radius_scale",
            top_level_key="bloom_radius_scale",
            default=defaults.radius_scale,
        ),
        "bloom_radius_scale",
    )
    min_radius = optional_float(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_min_radius",
            table_key="min_radius",
            top_level_key="bloom_min_radius",
            default=defaults.min_radius,
        ),
        "bloom_min_radius",
    )
    max_radius = optional_float(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_max_radius",
            table_key="max_radius",
            top_level_key="bloom_max_radius",
            default=defaults.max_radius,
        ),
        "bloom_max_radius",
    )
    strength = optional_float(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_strength",
            table_key="strength",
            top_level_key="bloom_strength",
            default=defaults.strength,
        ),
        "bloom_strength",
    )
    layers = optional_int(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_layers",
            table_key="layers",
            top_level_key="bloom_layers",
            default=defaults.layers,
        ),
        "bloom_layers",
    )
    color = optional_color(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_color",
            table_key="color",
            top_level_key="bloom_color",
            default=defaults.color,
        ),
        "bloom_color",
    )
    source = str(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_source",
            table_key="source",
            top_level_key="bloom_source",
            default=defaults.source,
        )
    )
    edge_width = optional_int(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_edge_width",
            table_key="edge_width",
            top_level_key="bloom_edge_width",
            default=defaults.edge_width,
        ),
        "bloom_edge_width",
    )
    intensity_power = optional_float(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_intensity_power",
            table_key="intensity_power",
            top_level_key="bloom_intensity_power",
            default=defaults.intensity_power,
        ),
        "bloom_intensity_power",
    )
    intensity_mode = str(
        _bloom_setting(
            cli_values,
            config,
            bloom_table,
            cli_key="bloom_intensity_mode",
            table_key="intensity_mode",
            top_level_key="bloom_intensity_mode",
            default=defaults.intensity_mode,
        )
    )

    if radius_scale is None or radius_scale < 0:
        raise KeyframeDataError("bloom_radius_scale must be non-negative.")
    if min_radius is None or min_radius < 0:
        raise KeyframeDataError("bloom_min_radius must be non-negative.")
    if max_radius is None or max_radius < min_radius:
        raise KeyframeDataError(
            "bloom_max_radius must be greater than or equal to bloom_min_radius."
        )
    if strength is None or strength < 0:
        raise KeyframeDataError("bloom_strength must be non-negative.")
    if layers is None or layers < 1:
        raise KeyframeDataError("bloom_layers must be at least 1.")
    if source not in BLOOM_SOURCES:
        raise KeyframeDataError(
            "bloom_source must be one of: " + ", ".join(BLOOM_SOURCES)
        )
    if edge_width is None or edge_width < 1:
        raise KeyframeDataError("bloom_edge_width must be at least 1.")
    if intensity_power is None or intensity_power < 0:
        raise KeyframeDataError("bloom_intensity_power must be non-negative.")
    if intensity_mode not in BLOOM_INTENSITY_MODES:
        raise KeyframeDataError(
            "bloom_intensity_mode must be one of: "
            + ", ".join(BLOOM_INTENSITY_MODES)
        )

    return BloomConfig(
        radius_scale=radius_scale,
        min_radius=min_radius,
        max_radius=max_radius,
        strength=strength,
        layers=layers,
        color=color,
        source=source,
        edge_width=edge_width,
        intensity_mode=intensity_mode,
        intensity_power=intensity_power,
    )


def resolve_export_formats(
    cli_values: object,
    config: Mapping[str, Any],
) -> set[str]:
    """Resolve requested animation export formats."""

    for export_format in EXPORT_FORMATS:
        if export_format in config:
            raise KeyframeDataError(
                f"Use exports = [...] instead of top-level '{export_format}'."
            )

    if hasattr(cli_values, "exports"):
        return _parse_cli_exports(getattr(cli_values, "exports"))
    if "exports" in config:
        return _parse_config_exports(config["exports"])

    return set()


def resolve_export_paths(
    output: Any,
    *,
    output_name: str,
    formats: set[str],
    project_root: Path,
) -> dict[str, Path]:
    """Resolve output file paths for requested export formats."""

    if output is None:
        return {
            export_format: project_root / "output" / f"{output_name}.{export_format}"
            for export_format in formats
        }

    output_path = resolve_project_path(output, project_root=project_root)
    if len(formats) == 1:
        export_format = next(iter(formats))
        if output_path.suffix:
            return {export_format: output_path}
        return {export_format: output_path.with_suffix(f".{export_format}")}

    return {
        export_format: output_path.with_suffix(f".{export_format}")
        for export_format in formats
    }


def resolve_project_path(value: Any, *, project_root: Path) -> Path:
    """Resolve relative paths from the project root."""

    path = Path(value)
    return path if path.is_absolute() else project_root / path


def display_path(path: Path, *, project_root: Path) -> str:
    """Return a compact display path when possible."""

    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def optional_float(value: Any, name: str) -> float | None:
    """Convert an optional config value to float."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise KeyframeDataError(f"{name} must be a number.") from exc


def optional_int(value: Any, name: str) -> int | None:
    """Convert an optional config value to int."""

    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise KeyframeDataError(f"{name} must be an integer.") from exc


def optional_bool(value: Any, name: str) -> bool:
    """Convert an optional config value to bool."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False

    raise KeyframeDataError(f"{name} must be true or false.")


def optional_color(value: Any, name: str) -> str | None:
    """Validate an optional Pillow color value."""

    if value is None:
        return None
    text = str(value).strip()
    if text.lower() == "word":
        return None
    try:
        ImageColor.getrgb(text)
    except ValueError as exc:
        raise KeyframeDataError(
            f"{name} must be 'word' or a valid Pillow color."
        ) from exc
    return text


def _bloom_table(config: Mapping[str, Any]) -> Mapping[str, Any]:
    value = config.get("bloom", {})
    if isinstance(value, Mapping):
        return value
    if isinstance(value, bool) or "bloom" not in config:
        return {}
    raise KeyframeDataError("Config key 'bloom' must be true, false, or a table.")


def _bloom_setting(
    cli_values: object,
    config: Mapping[str, Any],
    bloom_table: Mapping[str, Any],
    *,
    cli_key: str,
    table_key: str,
    top_level_key: str,
    default: Any,
) -> Any:
    if hasattr(cli_values, cli_key):
        return getattr(cli_values, cli_key)
    if table_key in bloom_table:
        return bloom_table[table_key]
    if top_level_key in config and not isinstance(config[top_level_key], Mapping):
        return config[top_level_key]
    return default


def _parse_cli_exports(values: Any) -> set[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = values
    else:
        raise KeyframeDataError("--exports must be a list of export formats.")

    return _parse_export_values(
        raw_values,
        source="--exports",
        allow_commas=True,
        allow_empty=False,
    )


def _parse_config_exports(values: Any) -> set[str]:
    if not isinstance(values, list):
        raise KeyframeDataError("Config key 'exports' must be a list.")

    return _parse_export_values(
        values,
        source="Config exports",
        allow_commas=False,
        allow_empty=True,
    )


def _parse_export_values(
    values: list[Any],
    *,
    source: str,
    allow_commas: bool,
    allow_empty: bool,
) -> set[str]:
    formats: set[str] = set()
    for value in values:
        parts = str(value).split(",") if allow_commas else [str(value)]
        for part in parts:
            export_format = part.strip().lower()
            if not export_format:
                continue
            if export_format not in EXPORT_FORMATS:
                raise KeyframeDataError(
                    f"{source} must contain only: " + ", ".join(EXPORT_FORMATS)
                )
            formats.add(export_format)

    if not formats and not allow_empty:
        raise KeyframeDataError("--exports must include at least one format.")
    return formats


def _parse_config_group_colors(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise KeyframeDataError("Config key 'group_colors' must be a table.")

    return {
        str(group): _normalize_hex_color(color, f"group_colors.{group}")
        for group, color in value.items()
    }


def _parse_cli_group_colors(values: Any) -> dict[str, str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list):
        raw_values = values
    else:
        raise KeyframeDataError("--group-color must be GROUP=#RRGGBB.")

    group_colors: dict[str, str] = {}
    for raw_value in raw_values:
        text = str(raw_value)
        if "=" not in text:
            raise KeyframeDataError("--group-color must be GROUP=#RRGGBB.")
        group, color = text.split("=", 1)
        group = group.strip()
        if not group:
            raise KeyframeDataError("--group-color group name cannot be blank.")
        group_colors[group] = _normalize_hex_color(color, f"group color for {group}")

    return group_colors


def _parse_color_stops(value: Any, name: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = _split_color_stop_text(value)
    elif isinstance(value, (list, tuple)):
        raw_values = []
        for item in value:
            raw_values.extend(_split_color_stop_text(str(item)))
    else:
        raise KeyframeDataError(f"{name} must be a list of at least two colors.")

    if len(raw_values) < 2:
        raise KeyframeDataError(f"{name} must contain at least two colors.")

    return tuple(
        _normalize_hex_color(color, f"{name}[{index}]")
        for index, color in enumerate(raw_values)
    )


def _split_color_stop_text(value: str) -> list[str]:
    return [
        token.strip()
        for token in value.replace(",", " ").split()
        if token.strip()
    ]


def _resolve_palette(
    cli_values: object,
    config: Mapping[str, Any],
    *,
    project_root: Path,
) -> tuple[str, ...]:
    cli_sets_palette = hasattr(cli_values, "palette")
    cli_sets_palette_file = hasattr(cli_values, "palette_file")

    if cli_sets_palette_file:
        return _load_palette_file(
            resolve_project_path(
                getattr(cli_values, "palette_file"),
                project_root=project_root,
            )
        )
    if cli_sets_palette:
        return _named_palette(getattr(cli_values, "palette"))
    if "palette_file" in config:
        return _load_palette_file(
            resolve_project_path(config["palette_file"], project_root=project_root)
        )

    palette_value = config.get("palette", DEFAULT_PALETTE_NAME)
    if isinstance(palette_value, list):
        return _normalize_palette(palette_value, "palette")
    return _named_palette(palette_value)


def _named_palette(value: Any) -> tuple[str, ...]:
    palette_name = str(value)
    if palette_name not in COLOR_PALETTES:
        raise KeyframeDataError(
            "palette must be one of: " + ", ".join(COLOR_PALETTES)
        )
    return COLOR_PALETTES[palette_name]


def _normalize_palette(values: list[Any], name: str) -> tuple[str, ...]:
    if not values:
        raise KeyframeDataError(f"{name} must contain at least one color.")
    return tuple(
        _normalize_hex_color(value, f"{name}[{index}]")
        for index, value in enumerate(values)
    )


def _load_palette_file(path: Path) -> tuple[str, ...]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise KeyframeDataError(f"Palette file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise KeyframeDataError(
            f"Palette file must be UTF-8 text, .hex, or .gpl: {path}"
        ) from exc

    if path.suffix.lower() == ".gpl":
        colors = _parse_gpl_palette(text, str(path))
    else:
        colors = _parse_text_palette(text, str(path))

    if not colors:
        raise KeyframeDataError(f"Palette file contains no colors: {path}")
    return tuple(colors)


def _parse_text_palette(text: str, name: str) -> list[str]:
    colors: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("#") and HEX_COLOR_PATTERN.match(stripped) is None:
            continue

        for token in stripped.replace(",", " ").split():
            if HEX_COLOR_PATTERN.match(token):
                colors.append(_normalize_hex_color(token, name))
                break

    return colors


def _parse_gpl_palette(text: str, name: str) -> list[str]:
    colors: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) < 3:
            continue
        try:
            red, green, blue = (int(parts[index]) for index in range(3))
        except ValueError:
            continue
        if not all(0 <= channel <= 255 for channel in (red, green, blue)):
            raise KeyframeDataError(f"Invalid RGB value in palette file {name}.")
        colors.append(f"#{red:02X}{green:02X}{blue:02X}")

    return colors


def _normalize_hex_color(value: Any, name: str) -> str:
    text = str(value).strip()
    match = HEX_COLOR_PATTERN.match(text)
    if match is None:
        raise KeyframeDataError(f"{name} must be a hex color: #RGB or #RRGGBB.")

    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(channel * 2 for channel in digits)

    return f"#{digits.upper()}"


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python < 3.11.
        try:
            import tomli as tomllib
        except ImportError as exc:
            raise KeyframeDataError(
                "TOML config requires Python 3.11+ or the 'tomli' package."
            ) from exc

    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise KeyframeDataError(f"Config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise KeyframeDataError(f"Config file is not valid TOML: {exc}") from exc
