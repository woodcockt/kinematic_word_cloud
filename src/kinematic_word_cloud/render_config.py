"""Render configuration loading and CLI override helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .data import KeyframeDataError
from .labels import LABEL_MODES, LABEL_POSITIONS, LabelConfig


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
