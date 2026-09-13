#!/usr/bin/env bash
# Install EasyEyes for the current user, or remove it with --uninstall.
set -euo pipefail

APP_ID="io.github.Gap_Shot.EasyEyes"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$DATA_HOME/easyeyes"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
PACKAGES=(python3 python3-gobject python3-cairo gtk3 gtk-layer-shell libayatana-appindicator-gtk3)

uninstall() {
    rm -rf "$LIB_DIR"
    rm -f "$BIN_DIR/easyeyes" "$APPS_DIR/$APP_ID.desktop" "$ICON_DIR/$APP_ID.svg" "$CONFIG_HOME/autostart/$APP_ID.desktop"
    echo "EasyEyes is uninstalled. Your settings are still in $CONFIG_HOME/easyeyes."
}

install_packages() {
    if ! command -v rpm >/dev/null || ! command -v dnf >/dev/null; then
        echo "This isn't Fedora, so install these packages (or your distro's equivalents) yourself: ${PACKAGES[*]}"
        return
    fi
    local missing=()
    for package in "${PACKAGES[@]}"; do
        rpm -q "$package" >/dev/null 2>&1 || missing+=("$package")
    done
    if ((${#missing[@]})); then
        echo "Installing Fedora packages: ${missing[*]}"
        sudo dnf install -y "${missing[@]}"
    fi
}

install_files() {
    rm -rf "$LIB_DIR"
    mkdir -p "$LIB_DIR" "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"
    cp -r "$SOURCE_DIR/easyeyes" "$LIB_DIR/"
    find "$LIB_DIR" -name __pycache__ -type d -prune -exec rm -rf {} +

    # -I keeps a user's PYTHONPATH or virtualenv from shadowing the system GTK bindings.
    cat >"$BIN_DIR/easyeyes" <<EOF
#!/bin/sh
exec /usr/bin/python3 -I -c 'import sys; sys.path.insert(0, "$LIB_DIR"); from easyeyes.__main__ import main; sys.exit(main(sys.argv))' "\$@"
EOF
    chmod +x "$BIN_DIR/easyeyes"

    sed "s|@EXEC@|$BIN_DIR/easyeyes|" "$SOURCE_DIR/easyeyes/data/$APP_ID.desktop.in" >"$APPS_DIR/$APP_ID.desktop"
    cp "$SOURCE_DIR/easyeyes/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICON_DIR/"
    if command -v update-desktop-database >/dev/null; then
        update-desktop-database -q "$APPS_DIR" || true
    fi
}

case "${1:-}" in
    --uninstall)
        uninstall
        ;;
    "")
        install_packages
        install_files
        echo "EasyEyes is installed. Open it from the app menu or run: easyeyes"
        case ":$PATH:" in
            *":$BIN_DIR:"*) ;;
            *) echo "Note: $BIN_DIR isn't on your PATH, so the easyeyes command needs its full path there." ;;
        esac
        # A running EasyEyes owns its app ID on the session bus.
        if gdbus call --session --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
            --method org.freedesktop.DBus.NameHasOwner "$APP_ID" 2>/dev/null | grep -q true; then
            echo "EasyEyes is running; quit it from the tray and start it again to use this version."
        fi
        ;;
    *)
        echo "Usage: $0 [--uninstall]" >&2
        exit 2
        ;;
esac
