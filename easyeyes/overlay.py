"""The see-through layer-shell surfaces that draw the ruler and, in Move mode, catch all input."""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_foreign("cairo")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

from . import geometry  # noqa: E402
from .monitors import MonitorInfo, Monitors  # noqa: E402
from .motion import KeyMotion  # noqa: E402
from .ruler import Ruler  # noqa: E402
from .settings import color_rgb  # noqa: E402

_DIRECTIONS = {Gdk.KEY_Up: -1, Gdk.KEY_KP_Up: -1, Gdk.KEY_Down: 1, Gdk.KEY_KP_Down: 1}
_LEAVE_KEYS = {Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter}
_GLIDE_INTERVAL_MS = 16

_LABEL_TEXT = "Move mode"
_LABEL_MARGIN = 16  # px from the monitor's top-left corner
_LABEL_PADDING_X = 14
_LABEL_PADDING_Y = 8
_LABEL_GRAY = (0.33, 0.33, 0.33)


@dataclass(frozen=True)
class Scene:
    """Everything needed to draw the ruler on one monitor."""

    layout: geometry.RulerLayout
    rgb: tuple[float, float, float]
    opacity: float
    move_mode: bool


class OverlayWindow(Gtk.Window):
    """A transparent surface covering one monitor, above every window."""

    def __init__(self, monitor: MonitorInfo, overlays: Overlays) -> None:
        super().__init__()
        self.monitor = monitor
        self._overlays = overlays
        self._scene: Scene | None = None
        self._label: Pango.Layout | None = None
        self._capturing = None
        self._keyboard = None
        self._dragging = False

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "easyeyes")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor.monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        # Cover the whole monitor, panels included, instead of the space panels leave free.
        GtkLayerShell.set_exclusive_zone(self, -1)

        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK
                        | Gdk.EventMask.KEY_RELEASE_MASK | Gdk.EventMask.FOCUS_CHANGE_MASK)

        self.connect("size-allocate", self._on_size_allocate)
        self.connect("draw", self._on_draw)
        self.connect("button-press-event", self._on_button_press)
        self.connect("motion-notify-event", self._on_motion)
        self.connect("button-release-event", self._on_button_release)
        self.connect("key-press-event", lambda _w, event: overlays.key_pressed(event) or True)
        self.connect("key-release-event", lambda _w, event: overlays.key_released(event) or True)
        self.connect("focus-out-event", lambda *_: overlays.keyboard_lost() or False)

        self.set_capturing(False)
        self.set_keyboard_exclusive(False)

    def set_capturing(self, capturing: bool) -> None:
        """Catch clicks (Move mode) or let them fall through to the windows below."""
        if capturing == self._capturing:
            return
        # None means the whole surface takes input; an empty region means none of it does.
        # The state is recorded only after the call succeeds, so a failed release gets retried.
        self.input_shape_combine_region(None if capturing else cairo.Region())
        self._capturing = capturing
        self._dragging = False
        self.queue_draw()  # a commit carries the new input region to the compositor

    def set_keyboard_exclusive(self, exclusive: bool) -> None:
        if exclusive == self._keyboard:
            return
        mode = GtkLayerShell.KeyboardMode.EXCLUSIVE if exclusive else GtkLayerShell.KeyboardMode.NONE
        GtkLayerShell.set_keyboard_mode(self, mode)
        self._keyboard = exclusive
        self.queue_draw()

    def refresh(self) -> None:
        """Redraw only what changed: the strips the ruler left and entered, and the Move mode label."""
        old, scene = self._scene, self._overlays.scene_for(self)
        if scene == old:
            return
        label_changed = old is None or scene is None or (old.move_mode, old.opacity) != (scene.move_mode, scene.opacity)
        width = self.get_allocated_width()
        for changed in (old, scene):
            if changed is None:
                continue
            band = changed.layout.extent
            self.queue_draw_area(0, band.top, width, band.height)
            if label_changed and changed.move_mode:
                self.queue_draw_area(*self._label_rect())
        self._scene = scene

    def _on_size_allocate(self, *_args) -> None:
        self._scene = self._overlays.scene_for(self)
        self.queue_draw()

    def _on_draw(self, _widget, cr) -> bool:
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        scene = self._scene
        if scene is None:
            return True
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_source_rgba(*scene.rgb, scene.opacity)
        width = self.get_allocated_width()
        for band in (scene.layout.top_guide_line, scene.layout.bottom_guide_line):
            cr.rectangle(0, band.top, width, band.height)
        cr.fill()
        if scene.move_mode:
            x, y, box_width, box_height = self._label_rect()
            cr.set_source_rgba(*_LABEL_GRAY, scene.opacity)
            cr.rectangle(x, y, box_width, box_height)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 1)
            cr.move_to(x + _LABEL_PADDING_X, y + _LABEL_PADDING_Y)
            PangoCairo.show_layout(cr, self._label_layout())
        return True

    def _label_layout(self) -> Pango.Layout:
        if self._label is None:
            self._label = self.create_pango_layout(_LABEL_TEXT)
            font = self.get_pango_context().get_font_description().copy()
            font.set_size(round(font.get_size() * 1.25) if font.get_size() else 14 * Pango.SCALE)
            self._label.set_font_description(font)
        return self._label

    def _label_rect(self) -> tuple[int, int, int, int]:
        text_width, text_height = self._label_layout().get_pixel_size()
        return (_LABEL_MARGIN, _LABEL_MARGIN,
                text_width + 2 * _LABEL_PADDING_X, text_height + 2 * _LABEL_PADDING_Y)

    def _on_button_press(self, _widget, event) -> bool:
        if self._capturing and event.button == Gdk.BUTTON_PRIMARY and event.type == Gdk.EventType.BUTTON_PRESS:
            self._dragging = True
            self._overlays.place(self, event.y)
        return True

    def _on_motion(self, _widget, event) -> bool:
        if self._dragging:
            self._overlays.place(self, event.y)
        return True

    def _on_button_release(self, _widget, event) -> bool:
        if event.button == Gdk.BUTTON_PRIMARY:
            self._dragging = False
        return True


class Overlays:
    """Keeps an overlay on each monitor that needs one: the ruler's monitor, or every monitor in Move mode."""

    def __init__(self, ruler: Ruler, monitors: Monitors) -> None:
        self._ruler = ruler
        self._monitors = monitors
        self._windows: dict[str, OverlayWindow] = {}
        self._keyboard_owner: OverlayWindow | None = None
        self._ruler_monitor: str | None = None
        self._motion = KeyMotion()
        self._held_keycode: int | None = None
        self._glide_timer = 0

    def sync(self) -> None:
        """Create, remove and reconfigure overlays to match the ruler's state."""
        ruler = self._ruler
        if not ruler.move_mode:
            # Give the keyboard and mouse back before anything that could fail.
            self.release_input()
        connected = self._monitors.keys
        self._ruler_monitor = ruler.effective_monitor(connected)
        if not ruler.visible or self._ruler_monitor is None:
            wanted = set()
        elif ruler.move_mode:
            wanted = set(connected)
        else:
            wanted = {self._ruler_monitor}

        for key in [key for key in self._windows if key not in wanted]:
            window = self._windows.pop(key)
            if window is self._keyboard_owner:
                self._keyboard_owner = None
            window.destroy()
        for info in self._monitors.all:
            if info.key in wanted and info.key not in self._windows:
                self._windows[info.key] = OverlayWindow(info, self)

        if ruler.move_mode and self._keyboard_owner is None:
            # Keep the keyboard on one surface for the whole of Move mode, even if the ruler changes monitors.
            self._keyboard_owner = self._windows.get(self._ruler_monitor)

        for window in self._windows.values():
            window.set_capturing(ruler.move_mode)
            window.set_keyboard_exclusive(window is self._keyboard_owner)
            window.show_all()
            window.refresh()

    def release_input(self) -> None:
        """Stop catching keys and clicks on every overlay, one window at a time so a failure can't block the rest."""
        self._stop_motion()
        self._keyboard_owner = None
        for window in list(self._windows.values()):
            try:
                window.set_keyboard_exclusive(False)
                window.set_capturing(False)
            except Exception:
                traceback.print_exc()

    def rebuild(self) -> None:
        """Start over after monitors are plugged in or out, since old surfaces may point at gone monitors."""
        # Destroying the keyboard's surface can swallow the key-up, so stop any Glide first.
        self._stop_motion()
        for window in self._windows.values():
            window.destroy()
        self._windows.clear()
        self._keyboard_owner = None
        self.sync()

    def refresh(self) -> None:
        for window in self._windows.values():
            window.refresh()

    def scene_for(self, window: OverlayWindow) -> Scene | None:
        ruler = self._ruler
        height = window.get_allocated_height()
        if not ruler.visible or window.monitor.key != self._ruler_monitor or height < 2:
            return None
        settings = ruler.settings
        center = geometry.center_from_position(settings.ruler_position, height, settings.reading_window_height)
        return Scene(
            layout=geometry.layout(center, settings.reading_window_height, settings.guide_line_thickness),
            rgb=color_rgb(settings.color),
            opacity=settings.opacity,
            move_mode=ruler.move_mode,
        )

    def place(self, window: OverlayWindow, y: float) -> None:
        self._ruler.place(window.monitor.key, y, window.get_allocated_height())

    def key_pressed(self, event) -> None:
        # Leaving comes first and does as little as possible, so it keeps working if anything else breaks.
        alt_f9 = event.keyval == Gdk.KEY_F9 and event.state & Gdk.ModifierType.MOD1_MASK
        if event.keyval in _LEAVE_KEYS or alt_f9:
            try:
                self._ruler.leave_move_mode()
            finally:
                # Also release directly: if an earlier sync failed partway, leave_move_mode has nothing left to do.
                if not self._ruler.move_mode:
                    self.release_input()
            return
        direction = _DIRECTIONS.get(event.keyval)
        if direction is None:
            return  # every other key is ignored in Move mode
        self._held_keycode = event.hardware_keycode
        self._motion.press(direction, time.monotonic())
        if not self._glide_timer:
            self._glide_timer = GLib.timeout_add(_GLIDE_INTERVAL_MS, self._on_glide_timer)

    def key_released(self, event) -> None:
        # Match the physical key rather than its keyval, which can change mid-hold (NumLock, a layout switch).
        if not self._motion.held or event.hardware_keycode != self._held_keycode:
            return
        settings = self._ruler.settings
        distance = self._motion.release(self._motion.direction, time.monotonic(),
                                        settings.text_line_spacing, settings.glide_speed)
        self._held_keycode = None
        if distance:
            self._move_by(distance)

    def keyboard_lost(self) -> None:
        # The key-up may never arrive once focus is gone, so stop any Glide now.
        self._motion.cancel()
        self._held_keycode = None

    def _on_glide_timer(self) -> bool:
        if not self._motion.held:
            self._glide_timer = 0
            return GLib.SOURCE_REMOVE
        distance = self._motion.advance(time.monotonic(), self._ruler.settings.glide_speed)
        if distance:
            self._move_by(distance)
        return GLib.SOURCE_CONTINUE

    def _move_by(self, distance: float) -> None:
        window = self._windows.get(self._ruler_monitor)
        if window is not None:
            self._ruler.move_by(distance, window.get_allocated_height())

    def _stop_motion(self) -> None:
        self._motion.cancel()
        self._held_keycode = None
        if self._glide_timer:
            GLib.source_remove(self._glide_timer)
            self._glide_timer = 0
