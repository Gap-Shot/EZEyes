"""Naming and tracking the monitors the ruler can appear on.

Works with Gdk.Display and Gdk.Monitor objects but doesn't import GTK, so the naming logic stays testable.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MonitorInfo:
    key: str  # stable name saved in the settings
    label: str  # what the settings window shows
    monitor: object  # Gdk.Monitor


def assign_keys(monitors: Sequence[tuple[str | None, str | None, int, int]]) -> list[str]:
    """Keys from each monitor's (manufacturer, model, x, y).

    A monitor's key is its name, unless another connected monitor has the same name. Then its logical position is added,
    which stays put in a fixed layout, unlike the order the monitors are listed in.
    """
    names = [" ".join(part.strip() for part in (manufacturer, model) if part and part.strip()) or "Monitor"
             for manufacturer, model, _x, _y in monitors]
    counts = Counter(names)
    keys: list[str] = []
    for name, (_manufacturer, _model, x, y) in zip(names, monitors):
        key = name if counts[name] == 1 else f"{name} at {x},{y}"
        # Mirrored identical monitors share a position too, and every key must still be unique.
        unique, number = key, 1
        while unique in keys:
            number += 1
            unique = f"{key} #{number}"
        keys.append(unique)
    return keys


def describe(display) -> list[MonitorInfo]:
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    geometries = [monitor.get_geometry() for monitor in monitors]
    keys = assign_keys([(monitor.get_manufacturer(), monitor.get_model(), geometry.x, geometry.y)
                        for monitor, geometry in zip(monitors, geometries)])
    return [MonitorInfo(key, f"{key} ({geometry.width}×{geometry.height})", monitor)
            for key, monitor, geometry in zip(keys, monitors, geometries)]


class Monitors:
    """The connected monitors, kept current as they're plugged in and out or rearranged."""

    def __init__(self, display, on_change: Callable[[], None]) -> None:
        self._display = display
        self._on_change = on_change
        self.all = describe(display)
        for info in self.all:
            self._watch(info.monitor)
        display.connect("monitor-added", self._added)
        display.connect("monitor-removed", self._changed)

    @property
    def keys(self) -> list[str]:
        return [info.key for info in self.all]

    def _watch(self, monitor) -> None:
        # Identical monitors are told apart by position, which can change without one being plugged in or out.
        monitor.connect("notify::geometry", self._moved)

    def _added(self, _display, monitor) -> None:
        self._watch(monitor)
        self._changed()

    def _moved(self, *_args) -> None:
        if [info.key for info in describe(self._display)] != self.keys:
            self._changed()

    def _changed(self, *_args) -> None:
        self.all = describe(self._display)
        self._on_change()
