"""Reusable GPU price collection scaffold; live adapters are not implemented."""

__version__ = "0.1.0.dev0"

from .settings import ConfigurationError, Settings

__all__ = ["ConfigurationError", "Settings", "__version__"]
