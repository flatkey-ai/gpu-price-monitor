"""Reusable GPU price collection with JSON results and CSV serialization."""

__version__ = "0.20.0"

from .settings import ConfigurationError, Settings
from .collector import collect_prices
from .coverage import MAINSTREAM_GPU_MODELS, gpu_family, report_coverage
from .catalog_audit import report_catalog_audit
from .csv_export import (COMPACT_CSV_COLUMNS, COMPACT_CSV_HEADERS, CSV_COLUMNS, CSV_HEADERS,
                         CATALOG_CSV_COLUMNS, CATALOG_CSV_HEADERS, catalog_eligible_record,
                         MARKET_CSV_COLUMNS, MARKET_CSV_HEADERS,
                         market_eligible_quote, prices_to_csv, publishable_quote)

__all__ = ["ConfigurationError", "Settings", "collect_prices", "MAINSTREAM_GPU_MODELS",
           "gpu_family", "report_coverage", "report_catalog_audit", "CSV_COLUMNS", "CSV_HEADERS", "COMPACT_CSV_COLUMNS",
           "COMPACT_CSV_HEADERS", "MARKET_CSV_COLUMNS", "MARKET_CSV_HEADERS",
           "CATALOG_CSV_COLUMNS", "CATALOG_CSV_HEADERS", "catalog_eligible_record",
           "prices_to_csv", "publishable_quote", "market_eligible_quote", "__version__"]
