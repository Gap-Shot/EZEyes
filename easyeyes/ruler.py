"""The ruler's state and the rules for showing, hiding and moving it."""

from __future__ import annotations

import enum
import traceback
from collections.abc import Callable, Sequence
from dataclasses import replace

from . import geometry
from .settings import DEFAULTS, Settings, validated


class Change(enum.Flag):
    NONE = 0
    VISIBILITY = 1
    MOVE_MODE = 2
    POSITION = 4
    MONITOR = 8
    APPEARANCE = 16
    MOTION = 32  # text line spacing or glide speed


SETTINGS_CHANGES = Change.POSITION | Change.MONITOR | Change.APPEARANCE | Change.MOTION

_FIELD_CHANGES = {
    "color": Change.APPEARANCE,
    "opacity": Change.APPEARANCE,
    "guide_line_thickness": Change.APPEARANCE,
    "reading_window_height": Change.APPEARANCE,
    "ruler_position": Change.POSITION,
    "monitor": Change.MONITOR,
    "text_line_spacing": Change.MOTION,
    "glide_speed": Change.MOTION,
}

# "Reset to defaults" keeps the chosen monitor.
_RESET_FIELDS = [name for name in _FIELD_CHANGES if name != "monitor"]


class Ruler:
    def __init__(self, settings: Settings) -> None:
        self._settings = validated(settings)
        self._visible = False
        self._move_mode = False
        self._listeners: list[Callable[[Change], None]] = []

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def move_mode(self) -> bool:
        return self._move_mode

    def subscribe(self, listener: Callable[[Change], None]) -> None:
        self._listeners.append(listener)

    def show(self) -> None:
        if not self._visible:
            self._visible = True
            self._notify(Change.VISIBILITY)

    def hide(self) -> None:
        """Hide the ruler, which also ends Move mode."""
        if not self._visible:
            return
        change = Change.VISIBILITY
        if self._move_mode:
            self._move_mode = False
            change |= Change.MOVE_MODE
        self._visible = False
        self._notify(change)

    def toggle_visibility(self) -> None:
        if self._visible:
            self.hide()
        else:
            self.show()

    def enter_move_mode(self) -> None:
        """Turn on Move mode, showing the ruler if it's hidden."""
        if self._move_mode:
            return
        change = Change.MOVE_MODE
        if not self._visible:
            self._visible = True
            change |= Change.VISIBILITY
        self._move_mode = True
        self._notify(change)

    def leave_move_mode(self) -> None:
        if self._move_mode:
            self._move_mode = False
            self._notify(Change.MOVE_MODE)

    def toggle_move_mode(self) -> None:
        if self._move_mode:
            self.leave_move_mode()
        else:
            self.enter_move_mode()

    def effective_monitor(self, connected: Sequence[str]) -> str | None:
        """The monitor the ruler appears on: the saved one if it's connected, otherwise the first."""
        if self._settings.monitor in connected:
            return self._settings.monitor
        return connected[0] if connected else None

    def move_by(self, distance: float, monitor_height: float) -> None:
        """Step or Glide the ruler `distance` pixels on its monitor."""
        settings = self._settings
        self.update(ruler_position=geometry.moved_position(
            settings.ruler_position, distance, monitor_height, settings.reading_window_height))

    def place(self, monitor: str, y: float, monitor_height: float) -> None:
        """Put the middle of the reading window at `y` on `monitor`."""
        self.update(monitor=monitor, ruler_position=geometry.placed_position(
            y, monitor_height, self._settings.reading_window_height))

    def reset(self) -> None:
        self.update(**{name: getattr(DEFAULTS, name) for name in _RESET_FIELDS})

    def update(self, **changes) -> None:
        new = validated(replace(self._settings, **changes))
        change = Change.NONE
        for name, flag in _FIELD_CHANGES.items():
            if getattr(new, name) != getattr(self._settings, name):
                change |= flag
        if change:
            self._settings = new
            self._notify(change)

    def _notify(self, change: Change) -> None:
        # One failing listener mustn't stop the others, or the overlay could keep holding input.
        for listener in list(self._listeners):
            try:
                listener(change)
            except Exception:
                traceback.print_exc()
