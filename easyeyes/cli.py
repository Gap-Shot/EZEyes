"""The `easyeyes` command line."""

from __future__ import annotations

USAGE = """\
Usage: easyeyes [--autostart] [COMMAND]

Commands:
  settings     Open the settings window (the default)
  toggle       Show or hide the ruler
  move         Turn Move mode on or off
  quit         Quit EasyEyes

Options:
  --autostart  Start in the tray without opening a window
  -h, --help   Show this help"""

COMMANDS = ("settings", "toggle", "move", "quit")


class UsageError(Exception):
    pass


def parse(args: list[str]) -> str:
    """The command to run: one of COMMANDS, "help", or "none" for a login start that stays in the tray."""
    autostart = False
    command = None
    for arg in args:
        if arg in ("-h", "--help"):
            return "help"
        if arg == "--autostart":
            autostart = True
        elif arg in COMMANDS and command is None:
            command = arg
        else:
            raise UsageError(f"unexpected argument: {arg}")
    if command is None:
        return "none" if autostart else "settings"
    return command
