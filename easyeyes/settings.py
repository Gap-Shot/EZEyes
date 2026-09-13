"""Ruler settings: their defaults, their limits, and the file they're saved in."""

from __future__ import annotations

import json
import math
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .paths import config_home

_HEX_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


@dataclass(frozen=True)
class Settings:
    color: str = "#77DD77"
    opacity: float = 0.8
    guide_line_thickness: int = 2  # px
    reading_window_height: int = 24  # px
    ruler_position: float = 50.0  # percent of the monitor's height
    text_line_spacing: int = 24  # px
    glide_speed: float = 12.0  # px per second
    monitor: str | None = None  # a monitor key; None until one is chosen


DEFAULTS = Settings()

# Inclusive limits for the numeric settings.
LIMITS = {
    "opacity": (0.1, 1.0),
    "guide_line_thickness": (1, 100),
    "reading_window_height": (4, 400),
    "ruler_position": (0.0, 100.0),
    "text_line_spacing": (4, 400),
    "glide_speed": (1.0, 500.0),
}


def validated(settings: Settings) -> Settings:
    """A copy of `settings` with every field the right type and inside its limits."""
    values = {}
    for field in fields(Settings):
        name = field.name
        value = getattr(settings, name)
        default = getattr(DEFAULTS, name)
        if name == "color":
            valid = isinstance(value, str) and _HEX_COLOR.fullmatch(value)
            values[name] = value.upper() if valid else default
        elif name == "monitor":
            values[name] = value if isinstance(value, str) and value else None
        else:
            values[name] = _clamped(value, *LIMITS[name], default)
    return Settings(**values)


def _clamped(value, low, high, default):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    try:
        if not math.isfinite(value):
            return default
    except OverflowError:  # an int too large to be a float
        return default
    value = min(max(value, low), high)
    return round(value) if isinstance(default, int) else float(value)


def from_dict(data: object) -> Settings:
    if not isinstance(data, dict):
        return DEFAULTS
    names = {field.name for field in fields(Settings)}
    return validated(Settings(**{name: value for name, value in data.items() if name in names}))


def to_dict(settings: Settings) -> dict:
    data = asdict(settings)
    data["ruler_position"] = round(settings.ruler_position, 4)
    return data


def color_rgb(color: str) -> tuple[float, float, float]:
    """Red, green and blue between 0 and 1 for a "#RRGGBB" color."""
    return tuple(int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))


def settings_path() -> Path:
    return config_home() / "easyeyes" / "settings.json"


def load(path: Path) -> Settings:
    """The settings saved at `path`, or the defaults if there are none or they can't be used."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DEFAULTS
    except OSError as error:
        print(f"easyeyes: can't read {path}: {error}", file=sys.stderr)
        return DEFAULTS
    # ValueError covers invalid UTF-8, invalid JSON and integers past Python's digit limit.
    except (ValueError, RecursionError) as error:
        print(f"easyeyes: ignoring invalid settings in {path}: {error}", file=sys.stderr)
        return DEFAULTS
    return from_dict(data)


def save(settings: Settings, path: Path) -> None:
    """Replace the settings file atomically, writing through it if it's a symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path.resolve()
    text = json.dumps(to_dict(settings), indent=2) + "\n"
    # A unique temporary file, so two instances saving at once never write into the same one.
    file = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False)
    try:
        with file:
            file.write(text)
            if target.exists():  # keep its permissions; a new file stays private to the user
                os.fchmod(file.fileno(), target.stat().st_mode & 0o777)
        os.replace(file.name, target)
    except BaseException:
        Path(file.name).unlink(missing_ok=True)
        raise
