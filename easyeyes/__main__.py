"""Run EasyEyes: `python3 -m easyeyes [COMMAND]`."""

from __future__ import annotations

import sys

from . import cli


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
    try:
        from .app import EasyEyesApp
    except (ImportError, ValueError) as error:
        print(f"easyeyes: a required library is missing ({error}).\n"
              "Run install.sh to install EasyEyes and the Fedora packages it needs.", file=sys.stderr)
        return 1
    return EasyEyesApp().run(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
