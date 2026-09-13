#!/usr/bin/env bash
# Install EasyEyes for the current user, or remove it with --uninstall.
set -euo pipefail

APP_ID="io.github.Gap_Shot.EasyEyes"
SOURCE_DIR="$(cd -P -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# Ignore a relative XDG_*_HOME, as the XDG spec requires and easyeyes/paths.py does.
case "${XDG_DATA_HOME:-}" in /*) DATA_HOME="$XDG_DATA_HOME" ;; *) DATA_HOME="$HOME/.local/share" ;; esac
case "${XDG_CONFIG_HOME:-}" in /*) CONFIG_HOME="$XDG_CONFIG_HOME" ;; *) CONFIG_HOME="$HOME/.config" ;; esac
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$DATA_HOME/easyeyes"
APPS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
PACKAGES=(python3 python3-gobject python3-cairo gtk3 gtk-layer-shell libayatana-appindicator-gtk3)
STAGING_DIR=""

# Replacing or removing $LIB_DIR would delete the source if either one is inside the other.
check_overlap() {
    local lib_real
    if [ -d "$LIB_DIR" ]; then
        lib_real="$(cd -P -- "$LIB_DIR" && pwd -P)"
    elif [ -d "$DATA_HOME" ]; then
        lib_real="$(cd -P -- "$DATA_HOME" && pwd -P)/easyeyes"
    else
        return 0
    fi
    local source_prefix="${SOURCE_DIR%/}/" lib_prefix="${lib_real%/}/"
    if [[ "$lib_prefix" != "$source_prefix"* && "$source_prefix" != "$lib_prefix"* ]]; then
        return 0
    fi
    echo "EasyEyes installs into $LIB_DIR, which overlaps its source in $SOURCE_DIR, so this could delete the source." >&2
    echo "Move the source somewhere else, such as ~/src/EasyEyes, and run install.sh from there." >&2
    exit 1
}

# Print $1 as one single-quoted sh word.
sh_quote() {
    local quote="'" escaped="'\\''"
    printf "'%s'" "${1//"$quote"/"$escaped"}"
}

uninstall() {
    check_overlap
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
    mkdir -p "$DATA_HOME"
    check_overlap
    mkdir -p "$BIN_DIR" "$APPS_DIR" "$ICON_DIR"

    # Copy next to $LIB_DIR and swap the copy in, so a failed copy leaves the installed app as it was.
    STAGING_DIR="$(mktemp -d "$DATA_HOME/.easyeyes-install.XXXXXX")"
    trap 'rm -rf -- "$STAGING_DIR"' EXIT
    mkdir "$STAGING_DIR/new"
    cp -r "$SOURCE_DIR/easyeyes" "$STAGING_DIR/new/"
    find "$STAGING_DIR/new" -name __pycache__ -type d -prune -exec rm -rf {} +
    if [ -e "$LIB_DIR" ] || [ -L "$LIB_DIR" ]; then
        mv -- "$LIB_DIR" "$STAGING_DIR/old"
    fi
    mv -- "$STAGING_DIR/new" "$LIB_DIR"
    rm -rf -- "$STAGING_DIR"
    trap - EXIT

    # -I keeps a user's PYTHONPATH or virtualenv from shadowing the system GTK bindings.
    # The install path is a quoted sh word passed to Python as an argument, so no character in it can change the code.
    {
        printf '#!/bin/sh\nlib_dir=%s\n' "$(sh_quote "$LIB_DIR")"
        cat <<'EOF'
exec /usr/bin/python3 -I -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from easyeyes.__main__ import main; sys.exit(main(sys.argv))' "$lib_dir" "$@"
EOF
    } >"$BIN_DIR/easyeyes"
    chmod +x "$BIN_DIR/easyeyes"

    # Write Exec the way the autostart entry does, which is safe for any character in the path.
    /usr/bin/python3 -I -B -c '
import sys
source_dir, template, launcher, entry = sys.argv[1:]
sys.path.insert(0, source_dir)
from easyeyes.autostart import exec_program
with open(template, encoding="utf-8") as file:
    text = file.read().replace("@EXEC@", exec_program(launcher))
with open(entry, "w", encoding="utf-8") as file:
    file.write(text)
' "$SOURCE_DIR" "$SOURCE_DIR/easyeyes/data/$APP_ID.desktop.in" "$BIN_DIR/easyeyes" "$APPS_DIR/$APP_ID.desktop"
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
