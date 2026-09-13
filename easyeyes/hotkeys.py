"""Global hotkeys from the XDG GlobalShortcuts portal. The desktop owns the key bindings; EasyEyes only asks."""

from __future__ import annotations

import enum
import itertools
import sys
from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
REGISTRY_INTERFACE = "org.freedesktop.host.portal.Registry"

# Desktops may list shortcuts sorted by ID (KDE stores them that way), so the prefixes keep this order.
TOGGLE_RULER = "1-toggle-ruler"
MOVE_MODE = "2-move-mode"


@dataclass(frozen=True)
class Shortcut:
    id: str
    description: str
    preferred_trigger: str


SHORTCUTS = (
    Shortcut(TOGGLE_RULER, "Show or hide the ruler", "ALT+F8"),
    Shortcut(MOVE_MODE, "Turn Move mode on or off", "ALT+F9"),
)


class Status(enum.Enum):
    STARTING = "starting"
    READY = "ready"
    DECLINED = "declined"  # the user turned down the desktop's prompt
    UNAVAILABLE = "unavailable"  # no portal, or it failed


class GlobalShortcuts:
    def __init__(self, app_id: str, on_activated: Callable[[str], None], on_changed: Callable[[], None]) -> None:
        self._app_id = app_id
        self._on_activated = on_activated
        self._on_changed = on_changed
        self._bus: Gio.DBusConnection | None = None
        self._session: str | None = None
        self._tokens = itertools.count(1)
        self.status = Status.STARTING
        self.triggers = {shortcut.id: "" for shortcut in SHORTCUTS}  # shortcut id -> e.g. "Alt+F8"

    def start(self) -> None:
        # A private connection guarantees Register is the first portal call on it, as the portal requires.
        try:
            address = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
            self._bus = Gio.DBusConnection.new_for_address_sync(
                address,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None)
        except GLib.Error as error:
            self._fail(error)
            return
        for signal, handler in (("Activated", self._on_activated_signal),
                                ("ShortcutsChanged", self._on_shortcuts_changed_signal)):
            self._bus.signal_subscribe(PORTAL_NAME, SHORTCUTS_INTERFACE, signal, PORTAL_PATH, None,
                                       Gio.DBusSignalFlags.NONE, handler)
        self._call(REGISTRY_INTERFACE, "Register", GLib.Variant("(sa{sv})", (self._app_id, {})), self._on_registered)

    def configure(self) -> bool:
        """Open the desktop's shortcut settings. False if there's nowhere to send the user."""
        if GLib.find_program_in_path("systemsettings"):
            try:
                Gio.Subprocess.new(["systemsettings", "kcm_keys", "--args", self._app_id], Gio.SubprocessFlags.NONE)
                return True
            except GLib.Error as error:
                _log(f"can't open KDE's shortcut settings: {error.message}")
        if self._session is not None:
            params = GLib.Variant("(osa{sv})", (self._session, "", {}))
            self._call(SHORTCUTS_INTERFACE, "ConfigureShortcuts", params,
                       lambda _reply, error: error and _log(f"can't open shortcut settings: {error.message}"))
            return True
        return False

    def _on_registered(self, _reply, error) -> None:
        if error is not None:
            # Usually means the desktop file isn't installed yet; hotkeys may still work without an app ID.
            _log(f"portal didn't register the app ID: {error.message}")
        self._request("CreateSession", lambda token: GLib.Variant("(a{sv})", ({
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", "easyeyes"),
        },)), self._on_session_created)

    def _on_session_created(self, response: int, results: dict) -> None:
        if response != 0:
            self._fail(f"portal refused a session (response {response})")
            return
        self._session = results["session_handle"]
        shortcuts = [(shortcut.id, {"description": GLib.Variant("s", shortcut.description),
                                    "preferred_trigger": GLib.Variant("s", shortcut.preferred_trigger)})
                     for shortcut in SHORTCUTS]
        self._request("BindShortcuts", lambda token: GLib.Variant("(oa(sa{sv})sa{sv})", (
            self._session, shortcuts, "", {"handle_token": GLib.Variant("s", token)})), self._on_bound)

    def _on_bound(self, response: int, results: dict) -> None:
        if response == 1:
            self.status = Status.DECLINED
            self._on_changed()
            return
        if response != 0:
            self._fail(f"portal didn't bind the hotkeys (response {response})")
            return
        self._apply(results.get("shortcuts", []))
        self.status = Status.READY
        self._on_changed()

    def _on_activated_signal(self, _bus, _sender, _path, _interface, _signal, params) -> None:
        session, shortcut_id, _timestamp, _options = params.unpack()
        if session == self._session:
            self._on_activated(shortcut_id)

    def _on_shortcuts_changed_signal(self, _bus, _sender, _path, _interface, _signal, params) -> None:
        session, shortcuts = params.unpack()
        if session == self._session:
            self._apply(shortcuts)
            self._on_changed()

    def _apply(self, shortcuts) -> None:
        for shortcut_id, properties in shortcuts:
            if shortcut_id in self.triggers:
                self.triggers[shortcut_id] = properties.get("trigger_description", "")

    def _request(self, method: str, build_params: Callable[[str], GLib.Variant],
                 on_response: Callable[[int, dict], None]) -> None:
        """Call a portal method whose answer arrives later as a Response signal on a Request object."""
        token = f"easyeyes{next(self._tokens)}"
        sender = self._bus.get_unique_name().lstrip(":").replace(".", "_")
        handle = f"{PORTAL_PATH}/request/{sender}/{token}"
        subscription = 0

        def on_response_signal(bus, _sender, _path, _interface, _signal, params):
            bus.signal_unsubscribe(subscription)
            response, results = params.unpack()
            on_response(response, results)

        def on_reply(_reply, error):
            if error is not None:
                self._bus.signal_unsubscribe(subscription)
                self._fail(error)

        # Subscribe before calling so a fast Response can't be missed.
        subscription = self._bus.signal_subscribe(PORTAL_NAME, REQUEST_INTERFACE, "Response", handle, None,
                                                  Gio.DBusSignalFlags.NONE, on_response_signal)
        self._call(SHORTCUTS_INTERFACE, method, build_params(token), on_reply)

    def _call(self, interface: str, method: str, params: GLib.Variant, callback) -> None:
        def on_finished(bus, result, _data):
            try:
                reply = bus.call_finish(result)
            except GLib.Error as error:
                callback(None, error)
            else:
                callback(reply, None)

        self._bus.call(PORTAL_NAME, PORTAL_PATH, interface, method, params, None,
                       Gio.DBusCallFlags.NONE, -1, None, on_finished, None)

    def _fail(self, error) -> None:
        _log(f"hotkeys unavailable: {getattr(error, 'message', error)}")
        self.status = Status.UNAVAILABLE
        self._on_changed()


def _log(message: str) -> None:
    print(f"easyeyes: {message}", file=sys.stderr)
