"""Reusable GPU price collection with JSON-serializable results."""

__version__ = "0.2.0"

from .settings import ConfigurationError, Settings
from .collector import collect_prices

__all__ = ["ConfigurationError", "Settings", "collect_prices", "__version__"]
