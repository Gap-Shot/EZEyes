"""Starting EasyEyes at login with an XDG autostart entry.

The entry file itself is the setting, so turning autostart on or off in the desktop's own settings shows up here too.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import APP_ID
from .paths import config_home

# Characters that force an Exec argument to be quoted (Desktop Entry spec).
_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")


def autostart_path() -> Path:
    return config_home() / "autostart" / f"{APP_ID}.desktop"


def launcher() -> str:
    return shutil.which("easyeyes") or str(Path.home() / ".local" / "bin" / "easyeyes")


def exec_argument(argument: str) -> str:
    """Quote one Exec argument per the Desktop Entry spec."""
    if argument and not _RESERVED.intersection(argument):
        return argument.replace("%", "%%")
    escaped = "".join("\\" + char if char in '"`$\\' else char for char in argument)
    # The general string escaping applies on top of the quoting rule, so backslashes double again.
    return '"' + escaped.replace("\\", "\\\\").replace("%", "%%") + '"'


def entry(executable: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=EasyEyes\n"
        "Comment=Draw a reading ruler over every window\n"
        f"Exec={exec_argument(executable)} --autostart\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
    )


def is_enabled(path: Path | None = None) -> bool:
    path = path or autostart_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return not any(line.strip().replace(" ", "").lower() == "hidden=true" for line in lines)


def set_enabled(enabled: bool, path: Path | None = None, executable: str | None = None) -> None:
    path = path or autostart_path()
    if enabled:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(entry(executable or launcher()), encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
