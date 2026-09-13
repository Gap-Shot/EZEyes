"""Run EasyEyes: `python3 -m easyeyes [COMMAND]`."""

from __future__ import annotations

import sys

from . import cli

# The GObject Introspection namespaces the app imports, and the versions it needs.
_NAMESPACES = {
    "Gdk": "3.0",
    "Gtk": "3.0",
    "GtkLayerShell": "0.1",
    "AyatanaAppIndicator3": "0.1",
    "Pango": "1.0",
    "PangoCairo": "1.0",
}


def main(argv: list[str]) -> int:
    # Check the arguments here so a typo never reaches an EasyEyes that's already running.
    try:
        command = cli.parse(argv[1:])
    except cli.UsageError as error:
        print(f"easyeyes: {error}\n\n{cli.USAGE}", file=sys.stderr)
        return 2
    if command == "help":
        print(cli.USAGE)
        return 0
    # Check the libraries here, so an error while importing the app itself isn't mistaken for a missing package.
    try:
        import cairo  # noqa: F401
        import gi
        for namespace, version in _NAMESPACES.items():
            gi.require_version(namespace, version)
    except (ImportError, ValueError) as error:
        print(f"easyeyes: a required library is missing ({error}).\n"
              "Run install.sh to install EasyEyes and the Fedora packages it needs.", file=sys.stderr)
        return 1
    from .app import EasyEyesApp
    return EasyEyesApp().run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
