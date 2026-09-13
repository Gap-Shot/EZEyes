"""Standard locations EasyEyes reads and writes."""

import os
from pathlib import Path


def config_home() -> Path:
    """The XDG config directory, ignoring a relative XDG_CONFIG_HOME as the spec requires."""
    value = os.environ.get("XDG_CONFIG_HOME", "")
    return Path(value) if os.path.isabs(value) else Path.home() / ".config"
