"""Naming and tracking the monitors the ruler can appear on.

Works with Gdk.Display and Gdk.Monitor objects but doesn't import GTK, so the naming logic stays testable.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorInfo:
    key: str  # stable name saved in the settings
    label: str  # what the settings window shows
    monitor: object  # Gdk.Monitor


def assign_keys(names: Sequence[tuple[str | None, str | None]]) -> list[str]:
    """Keys from each monitor's (manufacturer, model), numbering identical monitors."""
    keys = []
    seen: dict[str, int] = {}
    for index, (manufacturer, model) in enumerate(names):
        base = " ".join(part.strip() for part in (manufacturer, model) if part and part.strip())
        base = base or f"Monitor {index + 1}"
        seen[base] = seen.get(base, 0) + 1
        keys.append(base if seen[base] == 1 else f"{base} #{seen[base]}")
    return keys


def describe(display) -> list[MonitorInfo]:
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    keys = assign_keys([(monitor.get_manufacturer(), monitor.get_model()) for monitor in monitors])
    infos = []
    for key, monitor in zip(keys, monitors):
        geometry = monitor.get_geometry()
        infos.append(MonitorInfo(key, f"{key} ({geometry.width}×{geometry.height})", monitor))
    return infos


class Monitors:
    """The connected monitors, kept current as they're plugged in and out."""

    def __init__(self, display, on_change: Callable[[], None]) -> None:
        self._display = display
        self._on_change = on_change
        self.all = describe(display)
        display.connect("monitor-added", self._changed)
        display.connect("monitor-removed", self._changed)

    @property
    def keys(self) -> list[str]:
        return [info.key for info in self.all]

    def _changed(self, *_args) -> None:
        self.all = describe(self._display)
        self._on_change()
