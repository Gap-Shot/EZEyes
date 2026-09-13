"""Global hotkeys from the XDG GlobalShortcuts portal. The desktop owns the key bindings; EasyEyes only asks."""

from __future__ import annotations

import enum
import itertools
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
REGISTRY_INTERFACE = "org.freedesktop.host.portal.Registry"

# CreateSession never waits on the user, so no answer by then means none is coming. BindShortcuts has no
# timeout: the desktop may be showing an approval dialog.
CREATE_SESSION_TIMEOUT_SECONDS = 30
# A session the portal closes again this soon after EasyEyes re-created it stays closed, so a portal that
# closes every session can't start a loop.
SESSION_RETRY_INTERVAL_SECONDS = 60

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
        self._portal: str | None = None  # the running portal's unique bus name
        self._session: str | None = None
        self._session_closed_subscription = 0
        self._requests: dict[int, int] = {}  # Response subscription -> timeout source, or 0
        self._generation = 0  # bumped whenever the portal or session goes away, so late answers are ignored
        self._last_session_retry = float("-inf")
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
        # A restarted portal has forgotten the app ID, session and bindings, so each time it appears we set
        # them all up again, starting with Register.
        Gio.bus_watch_name_on_connection(self._bus, PORTAL_NAME, Gio.BusNameWatcherFlags.AUTO_START,
                                         self._on_portal_appeared, self._on_portal_vanished)

    def configure(self) -> bool:
        """Open the desktop's shortcut settings. False if there's nowhere to send the user."""
        # systemsettings is often installed alongside other desktops, where KDE's shortcuts do nothing.
        on_kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").split(":")
        if on_kde and GLib.find_program_in_path("systemsettings"):
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

    def _on_portal_appeared(self, _bus, _name, owner: str) -> None:
        self._forget_session()
        self._portal = owner
        self._last_session_retry = float("-inf")
        self.status = Status.STARTING
        self._on_changed()
        self._call(REGISTRY_INTERFACE, "Register", GLib.Variant("(sa{sv})", (self._app_id, {})), self._on_registered)

    def _on_portal_vanished(self, _bus, _name) -> None:
        self._forget_session()
        self._portal = None
        self._fail("the portal isn't running")

    def _on_registered(self, _reply, error) -> None:
        if error is not None:
            # Usually means the desktop file isn't installed yet; hotkeys may still work without an app ID.
            _log(f"portal didn't register the app ID: {error.message}")
        self._create_session()

    def _create_session(self) -> None:
        self._request("CreateSession", lambda token: GLib.Variant("(a{sv})", ({
            "handle_token": GLib.Variant("s", token),
            "session_handle_token": GLib.Variant("s", "easyeyes"),
        },)), self._on_session_created, CREATE_SESSION_TIMEOUT_SECONDS)

    def _on_session_created(self, response: int, results: dict) -> None:
        if response != 0:
            self._fail(f"portal refused a session (response {response})")
            return
        session = results.get("session_handle")
        if not session:
            self._fail("portal created a session without a handle")
            return
        self._session = session
        self._session_closed_subscription = self._bus.signal_subscribe(
            self._portal, SESSION_INTERFACE, "Closed", session, None, Gio.DBusSignalFlags.NONE,
            self._current(self._on_session_closed))
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

    def _on_session_closed(self, *_signal) -> None:
        declined = self.status is Status.DECLINED
        self._forget_session()
        if declined:
            # A new session would ask the user again, and they've already said no.
            self._on_changed()
            return
        now = time.monotonic()
        if now - self._last_session_retry < SESSION_RETRY_INTERVAL_SECONDS:
            self._fail("the portal keeps closing the hotkey session")
            return
        _log("the portal closed the hotkey session; starting a new one")
        self._last_session_retry = now
        self.status = Status.STARTING
        self._on_changed()
        self._create_session()

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

    def _forget_session(self) -> None:
        """Drop the session, its triggers and any outstanding requests. Callers report the new status."""
        self._generation += 1
        for subscription, timeout in self._requests.items():
            self._bus.signal_unsubscribe(subscription)
            if timeout:
                GLib.source_remove(timeout)
        self._requests.clear()
        if self._session_closed_subscription:
            self._bus.signal_unsubscribe(self._session_closed_subscription)
            self._session_closed_subscription = 0
        self._session = None
        for shortcut_id in self.triggers:
            self.triggers[shortcut_id] = ""

    def _current(self, callback: Callable) -> Callable:
        """`callback`, made to do nothing once the portal instance or session it was meant for is gone."""
        generation = self._generation

        def guarded(*args):
            if generation == self._generation:
                return callback(*args)

        return guarded

    def _request(self, method: str, build_params: Callable[[str], GLib.Variant],
                 on_response: Callable[[int, dict], None], timeout_seconds: float | None = None) -> None:
        """Call a portal method whose answer arrives later as a Response signal on a Request object."""
        token = f"easyeyes{next(self._tokens)}"
        sender = self._bus.get_unique_name().lstrip(":").replace(".", "_")
        handle = f"{PORTAL_PATH}/request/{sender}/{token}"
        subscription = 0

        def finish() -> None:
            timeout = self._requests.pop(subscription, 0)
            if timeout:
                GLib.source_remove(timeout)
            self._bus.signal_unsubscribe(subscription)

        def on_response_signal(_bus, _sender, _path, _interface, _signal, params):
            finish()
            response, results = params.unpack()
            on_response(response, results)

        def on_reply(_reply, error):
            if error is not None:
                finish()
                self._fail(error)

        def on_timeout():
            self._requests[subscription] = 0  # this source is already being removed
            finish()
            self._fail(f"portal didn't answer {method}")
            return GLib.SOURCE_REMOVE

        # Subscribe before calling so a fast Response can't be missed.
        subscription = self._bus.signal_subscribe(self._portal, REQUEST_INTERFACE, "Response", handle, None,
                                                  Gio.DBusSignalFlags.NONE, self._current(on_response_signal))
        self._requests[subscription] = (GLib.timeout_add(round(timeout_seconds * 1000), self._current(on_timeout))
                                        if timeout_seconds else 0)
        self._call(SHORTCUTS_INTERFACE, method, build_params(token), on_reply)

    def _call(self, interface: str, method: str, params: GLib.Variant, callback) -> None:
        def on_finished(bus, result, _data):
            try:
                reply = bus.call_finish(result)
            except GLib.Error as error:
                callback(None, error)
            else:
                callback(reply, None)

        # Addressed to the instance the name watcher reported, so a call meant for a portal that just exited
        # can't reach its replacement ahead of Register.
        self._bus.call(self._portal, PORTAL_PATH, interface, method, params, None,
                       Gio.DBusCallFlags.NONE, -1, None, self._current(on_finished), None)

    def _fail(self, error) -> None:
        _log(f"hotkeys unavailable: {getattr(error, 'message', error)}")
        self.status = Status.UNAVAILABLE
        self._on_changed()


def _log(message: str) -> None:
    print(f"easyeyes: {message}", file=sys.stderr)
