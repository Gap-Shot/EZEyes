"""The settings window. Every change applies immediately; the app saves it."""

from __future__ import annotations

import sys
from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import APP_ID, autostart  # noqa: E402
from .hotkeys import MOVE_MODE, TOGGLE_RULER, GlobalShortcuts, Status  # noqa: E402
from .monitors import Monitors  # noqa: E402
from .ruler import Change, Ruler  # noqa: E402
from .settings import LIMITS  # noqa: E402

_NO_HOTKEYS = ("Your desktop didn't give EasyEyes any hotkeys. You can bind keys in your compositor's "
               "config to the commands “easyeyes toggle” and “easyeyes move”.")
_DECLINED = "The hotkeys weren't approved. Use Change… to set them in your desktop's shortcut settings."


class SettingsWindow(Gtk.Window):
    def __init__(self, ruler: Ruler, monitors: Monitors, hotkeys: GlobalShortcuts,
                 configure_hotkeys: Callable[[], bool]) -> None:
        super().__init__(title="EasyEyes Settings")
        self._ruler = ruler
        self._monitors = monitors
        self._hotkeys = hotkeys
        self._configure_hotkeys = configure_hotkeys
        self._updating = False
        self._row = 0

        self.set_icon_name(APP_ID)
        self.set_default_size(480, -1)
        self.connect("delete-event", lambda *_: self.hide() or True)

        self._grid = Gtk.Grid(column_spacing=24, row_spacing=10, margin=18)
        self.add(self._grid)

        self._show = Gtk.Switch(halign=Gtk.Align.END)
        self._show.connect("notify::active", self._on_show_toggled)
        self._add_row("Show ruler", self._show)

        self._add_heading("Appearance")
        self._color = Gtk.ColorButton(halign=Gtk.Align.END, use_alpha=False)
        self._color.connect("color-set", self._on_color_set)
        self._add_row("Color", self._color)
        self._opacity = self._scale(10, 100, 1, 0, "{:.0f}%",
                                    lambda value: self._update(opacity=value / 100))
        self._add_row("Opacity", self._opacity)
        self._thickness = self._add_number("Guide line thickness", "guide_line_thickness", "px")
        self._window_height = self._add_number("Reading window height", "reading_window_height", "px")

        self._add_heading("Position")
        self._position = self._scale(*LIMITS["ruler_position"], 0.5, 1, "{:.1f}%",
                                     lambda value: self._update(ruler_position=value))
        self._add_row("Ruler position", self._position)
        self._monitor = Gtk.ComboBoxText(halign=Gtk.Align.END)
        self._monitor.connect("changed", self._on_monitor_changed)
        self._add_row("Monitor", self._monitor)

        self._add_heading("Moving")
        self._line_spacing = self._add_number("Text line spacing", "text_line_spacing", "px")
        self._glide_speed = self._add_number("Glide speed", "glide_speed", "px/s")

        self._add_heading("Hotkeys")
        self._toggle_trigger = Gtk.Label(halign=Gtk.Align.END)
        self._add_row("Show or hide ruler", self._toggle_trigger)
        self._move_trigger = Gtk.Label(halign=Gtk.Align.END)
        self._add_row("Move mode", self._move_trigger)
        self._hotkey_note = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        self._hotkey_note.get_style_context().add_class("dim-label")
        self._grid.attach(self._hotkey_note, 0, self._row, 2, 1)
        self._row += 1
        change = Gtk.Button(label="Change…", halign=Gtk.Align.END)
        change.connect("clicked", self._on_change_hotkeys)
        self._grid.attach(change, 1, self._row, 1, 1)
        self._row += 1

        self._add_heading("Startup")
        self._login = Gtk.Switch(halign=Gtk.Align.END)
        self._login.connect("notify::active", self._on_login_toggled)
        self._add_row("Start at login", self._login)

        reset = Gtk.Button(label="Reset to defaults", halign=Gtk.Align.START, margin_top=12)
        reset.set_tooltip_text("Restores every ruler setting except the monitor")
        reset.connect("clicked", lambda _button: self._ruler.reset())
        self._grid.attach(reset, 0, self._row, 2, 1)

        self._grid.show_all()
        self.refresh()

    def refresh(self, change: Change | None = None) -> None:
        """Show the current state. `change` limits the work to what changed; None refreshes everything."""
        self._updating = True
        try:
            settings = self._ruler.settings
            everything = change is None
            if everything or change & Change.VISIBILITY:
                self._show.set_active(self._ruler.visible)
            if everything or change & Change.APPEARANCE:
                rgba = Gdk.RGBA()
                rgba.parse(settings.color)
                self._color.set_rgba(rgba)
                self._opacity.set_value(settings.opacity * 100)
                self._thickness.set_value(settings.guide_line_thickness)
                self._window_height.set_value(settings.reading_window_height)
            if everything or change & Change.POSITION:
                self._position.set_value(settings.ruler_position)
            if everything or change & Change.MONITOR:
                self._monitor.remove_all()
                for info in self._monitors.all:
                    self._monitor.append(info.key, info.label)
                self._monitor.set_active_id(self._ruler.effective_monitor(self._monitors.keys))
            if everything or change & Change.MOTION:
                self._line_spacing.set_value(settings.text_line_spacing)
                self._glide_speed.set_value(settings.glide_speed)
            if everything:
                self._login.set_active(autostart.is_enabled())
                self.refresh_hotkeys()
        finally:
            self._updating = False

    def refresh_hotkeys(self) -> None:
        for label, shortcut_id in ((self._toggle_trigger, TOGGLE_RULER), (self._move_trigger, MOVE_MODE)):
            label.set_text(self._hotkeys.triggers.get(shortcut_id) or "Not assigned")
        notes = {Status.UNAVAILABLE: _NO_HOTKEYS, Status.DECLINED: _DECLINED}
        note = notes.get(self._hotkeys.status, "")
        self._hotkey_note.set_text(note)
        self._hotkey_note.set_visible(bool(note))

    def _add_heading(self, text: str) -> None:
        label = Gtk.Label(xalign=0, margin_top=12)
        label.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
        self._grid.attach(label, 0, self._row, 2, 1)
        self._row += 1

    def _add_row(self, text: str, widget: Gtk.Widget) -> None:
        self._grid.attach(Gtk.Label(label=text, xalign=0, hexpand=True), 0, self._row, 1, 1)
        self._grid.attach(widget, 1, self._row, 1, 1)
        self._row += 1

    def _add_number(self, text: str, name: str, unit: str) -> Gtk.SpinButton:
        low, high = LIMITS[name]
        spin = Gtk.SpinButton.new_with_range(low, high, 1)
        spin.connect("value-changed", lambda button: self._update(**{name: button.get_value()}))
        box = Gtk.Box(spacing=6, halign=Gtk.Align.END)
        box.pack_start(spin, False, False, 0)
        box.pack_start(Gtk.Label(label=unit, xalign=0, width_chars=4), False, False, 0)
        self._add_row(text, box)
        return spin

    def _scale(self, low: float, high: float, step: float, digits: int, text: str,
               on_change: Callable[[float], None]) -> Gtk.Scale:
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
        scale.set_digits(digits)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_size_request(220, -1)
        scale.set_halign(Gtk.Align.END)
        scale.connect("format-value", lambda _scale, value: text.format(value))
        scale.connect("value-changed", lambda widget: self._updating or on_change(widget.get_value()))
        return scale

    def _update(self, **changes) -> None:
        if not self._updating:
            self._ruler.update(**changes)

    def _on_show_toggled(self, switch: Gtk.Switch, _param) -> None:
        if not self._updating and switch.get_active() != self._ruler.visible:
            self._ruler.toggle_visibility()

    def _on_color_set(self, button: Gtk.ColorButton) -> None:
        rgba = button.get_rgba()
        channels = (round(channel * 255) for channel in (rgba.red, rgba.green, rgba.blue))
        self._update(color="#{:02X}{:02X}{:02X}".format(*channels))

    def _on_monitor_changed(self, combo: Gtk.ComboBoxText) -> None:
        key = combo.get_active_id()
        if key is not None:
            self._update(monitor=key)

    def _on_change_hotkeys(self, _button: Gtk.Button) -> None:
        if not self._configure_hotkeys():
            self._hotkey_note.set_text(_NO_HOTKEYS)
            self._hotkey_note.show()

    def _on_login_toggled(self, switch: Gtk.Switch, _param) -> None:
        if self._updating:
            return
        try:
            autostart.set_enabled(switch.get_active())
        except OSError as error:
            print(f"easyeyes: can't change start at login: {error}", file=sys.stderr)
            self._updating = True
            switch.set_active(autostart.is_enabled())
            self._updating = False
