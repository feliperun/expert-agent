"""expert — CLI for expert-agent (init, validate, sync, ask, sessions)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("expert-agent")
except PackageNotFoundError:
    __version__ = "0.0.0+local"
