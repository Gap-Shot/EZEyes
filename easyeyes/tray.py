"""The tray icon and its menu."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator  # noqa: E402
from gi.repository import Gtk  # noqa: E402

from . import APP_ID  # noqa: E402

ICON_THEME_PATH = Path(__file__).parent / "data" / "icons"


class Tray:
    """A left click opens the menu (Ayatana has no left-click action); a middle click opens settings."""

    def __init__(self, toggle_ruler: Callable[[], None], move_ruler: Callable[[], None],
                 open_settings: Callable[[], None], quit_app: Callable[[], None]) -> None:
        self._indicator = AppIndicator.Indicator.new_with_path(
            APP_ID, APP_ID, AppIndicator.IndicatorCategory.APPLICATION_STATUS, str(ICON_THEME_PATH))
        self._indicator.set_title("EasyEyes")

        menu = Gtk.Menu()
        self._toggle_item = self._add(menu, "Show ruler", toggle_ruler)
        self._add(menu, "Move ruler", move_ruler)
        settings_item = self._add(menu, "Settings", open_settings)
        menu.append(Gtk.SeparatorMenuItem())
        self._add(menu, "Quit", quit_app)
        menu.show_all()

        self._indicator.set_menu(menu)
        self._indicator.set_secondary_activate_target(settings_item)
        self._indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    def set_ruler_visible(self, visible: bool) -> None:
        self._toggle_item.set_label("Hide ruler" if visible else "Show ruler")

    @staticmethod
    def _add(menu: Gtk.Menu, label: str, action: Callable[[], None]) -> Gtk.MenuItem:
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _item: action())
        menu.append(item)
        return item
