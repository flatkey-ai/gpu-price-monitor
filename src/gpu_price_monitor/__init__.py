"""Reusable GPU price collection with JSON-serializable results."""

__version__ = "0.6.1"

from .settings import ConfigurationError, Settings
from .collector import collect_prices
from .coverage import MAINSTREAM_GPU_MODELS, gpu_family, report_coverage

__all__ = ["ConfigurationError", "Settings", "collect_prices", "MAINSTREAM_GPU_MODELS",
           "gpu_family", "report_coverage", "__version__"]
