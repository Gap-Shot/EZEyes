"""The EasyEyes application: one background process that owns the ruler, tray icon, hotkeys and settings."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

from . import APP_ID, cli, settings  # noqa: E402
from .hotkeys import MOVE_MODE, TOGGLE_RULER, GlobalShortcuts  # noqa: E402
from .monitors import Monitors  # noqa: E402
from .overlay import Overlays  # noqa: E402
from .ruler import SETTINGS_CHANGES, Change, Ruler  # noqa: E402
from .settings_window import SettingsWindow  # noqa: E402
from .tray import Tray  # noqa: E402

_SAVE_DELAY_MS = 500


class EasyEyesApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._supported = True
        self._started = False
        self._settings_path = settings.settings_path()
        self._settings_window: SettingsWindow | None = None
        self._save_timer = 0

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        if not GtkLayerShell.is_supported():
            self._supported = False
            return
        try:
            self._start()
        except Exception:
            # Without hold() the process exits after this launch, instead of lingering broken on the app ID
            # and swallowing every later command.
            traceback.print_exc()
            return
        self._started = True
        self.hold()  # keep running with no windows open

    def _start(self) -> None:
        self.ruler = Ruler(settings.load(self._settings_path))
        self.monitors = Monitors(Gdk.Display.get_default(), self._on_monitors_changed)
        self.overlays = Overlays(self.ruler, self.monitors)
        self.tray = Tray(self.ruler.toggle_visibility, self.ruler.enter_move_mode, self.open_settings, self.quit)
        self.hotkeys = GlobalShortcuts(APP_ID, self._on_hotkey, self._on_hotkeys_changed)
        self.watchdog = Watchdog(self._save_now)

        self.ruler.subscribe(self._on_ruler_changed)
        if self.ruler.settings.monitor is None and self.monitors.keys:
            self.ruler.update(monitor=self.monitors.keys[0])
        self.hotkeys.start()

        for signum in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._on_signal)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        if not self._supported:
            self._show_unsupported()
            return 1
        if not self._started:
            command_line.printerr_literal("easyeyes: EasyEyes couldn't start; the error is shown above.\n")
            return 1
        try:
            command = cli.parse(command_line.get_arguments()[1:])
        except cli.UsageError as error:
            command_line.printerr_literal(f"easyeyes: {error}\n")
            return 2
        if command == "settings":
            self.open_settings()
        elif command == "toggle":
            self.ruler.toggle_visibility()
        elif command == "move":
            self.ruler.toggle_move_mode()
        elif command == "quit":
            self.quit()
        return 0

    def do_shutdown(self) -> None:
        if self._save_timer:
            GLib.source_remove(self._save_timer)
            self._save_now()
        Gtk.Application.do_shutdown(self)

    def open_settings(self) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self.ruler, self.monitors, self.hotkeys, self.hotkeys.configure)
            self.add_window(self._settings_window)
        else:
            self._settings_window.refresh()
        self._settings_window.present()

    def _on_ruler_changed(self, change: Change) -> None:
        # Arm the watchdog before the overlays take input, and disarm it only once they've let go.
        if self.ruler.move_mode:
            self.watchdog.armed = True
        if change & (Change.VISIBILITY | Change.MOVE_MODE | Change.MONITOR):
            self.overlays.sync()
        elif change & (Change.POSITION | Change.APPEARANCE):
            self.overlays.refresh()
        self.watchdog.armed = self.ruler.move_mode
        if change & Change.VISIBILITY:
            self.tray.set_ruler_visible(self.ruler.visible)
        if change & SETTINGS_CHANGES and not self._save_timer:
            self._save_timer = GLib.timeout_add(_SAVE_DELAY_MS, self._on_save_timer)
        if self._settings_window is not None:
            self._settings_window.refresh(change)

    def _on_monitors_changed(self) -> None:
        self.overlays.rebuild()
        if self._settings_window is not None:
            self._settings_window.refresh(Change.MONITOR)

    def _on_hotkey(self, shortcut_id: str) -> None:
        if shortcut_id == TOGGLE_RULER:
            self.ruler.toggle_visibility()
        elif shortcut_id == MOVE_MODE:
            self.ruler.toggle_move_mode()

    def _on_hotkeys_changed(self) -> None:
        if self._settings_window is not None:
            self._settings_window.refresh_hotkeys()

    def _on_save_timer(self) -> bool:
        self._save_timer = 0
        self._save_now()
        return GLib.SOURCE_REMOVE

    def _save_now(self) -> None:
        try:
            settings.save(self.ruler.settings, self._settings_path)
        except OSError as error:
            print(f"easyeyes: can't save settings to {self._settings_path}: {error}", file=sys.stderr)

    def _on_signal(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE

    def _show_unsupported(self) -> None:
        title = "EasyEyes can't run on this desktop"
        detail = ("EasyEyes needs a Wayland desktop that supports layer-shell, such as KDE Plasma, Hyprland "
                  "or Sway. GNOME on Wayland and X11 sessions aren't supported.")
        print(f"easyeyes: {title}. {detail}", file=sys.stderr)
        dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text=title)
        dialog.format_secondary_text(detail)
        dialog.run()
        dialog.destroy()


class Watchdog:
    """Quits EasyEyes if it stops responding while Move mode holds the keyboard and mouse, so you get them back."""

    STALL_SECONDS = 10
    SAVE_SECONDS = 2  # how long a last save may take before quitting anyway

    def __init__(self, save: Callable[[], None]) -> None:
        self.armed = False
        self._save = save
        self._heartbeat = time.monotonic()
        GLib.timeout_add(500, self._beat)
        threading.Thread(target=self._watch, name="easyeyes-watchdog", daemon=True).start()

    def _beat(self) -> bool:
        self._heartbeat = time.monotonic()
        return GLib.SOURCE_CONTINUE

    def _watch(self) -> None:
        while True:
            time.sleep(1)
            if self.armed and time.monotonic() - self._heartbeat > self.STALL_SECONDS:
                os.write(2, b"easyeyes: stopped responding in Move mode; quitting to release the keyboard and mouse\n")
                # Keep the ruler's latest position, but never let a slow disk hold the keyboard and mouse longer.
                saver = threading.Thread(target=self._save, name="easyeyes-last-save", daemon=True)
                saver.start()
                saver.join(self.SAVE_SECONDS)
                os._exit(3)
