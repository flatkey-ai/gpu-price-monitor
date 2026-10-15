"""Local collection-library configuration checks. No live collection yet."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import __version__
from .settings import ConfigurationError, PROVIDERS, SOURCES, Settings

FILTER_FIELDS = {
    "compute_countries", "sales_countries", "regions", "zones",
    "gpu_models", "gpu_counts", "billing_modes", "currencies",
}
BILLING_MODES = {"on_demand", "spot", "reserved", "monthly", "yearly"}


def validate_config(config: object) -> list[str]:
    """Check the collection-only scaffold format, not provider readiness."""
    if not isinstance(config, dict):
        return ["configuration must be a JSON object"]
    errors: list[str] = []
    if set(config) - {"schema_version", "request", "providers"}:
        errors.append("only schema_version, request and providers are supported; application services belong to the caller")
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        errors.append("schema_version must be 1")
    request = config.get("request")
    if not isinstance(request, dict) or set(request) != {"timeout_seconds", "max_retries"}:
        errors.append("request must contain timeout_seconds and max_retries only")
    else:
        try:
            Settings(timeout_seconds=request["timeout_seconds"], max_retries=request["max_retries"])
        except ConfigurationError:
            errors.append("request timeout_seconds must be finite in (0, 300] and max_retries an integer in [0, 10]")
    providers = config.get("providers")
    if not isinstance(providers, list) or not providers:
        return errors + ["providers must be a non-empty list"]
    seen: set[str] = set()
    for index, provider in enumerate(providers):
        prefix = f"providers[{index}]"
        if not isinstance(provider, dict):
            errors.append(f"{prefix} must be an object")
            continue
        if set(provider) != {"id", "enabled", "planned_source", "filters"}:
            errors.append(f"{prefix} must contain id, enabled, planned_source and filters only")
        provider_id = provider.get("id")
        if not isinstance(provider_id, str) or provider_id not in PROVIDERS:
            errors.append(f"{prefix}.id is not a known first-phase provider")
        elif provider_id in seen:
            errors.append(f"{prefix}.id is duplicated")
        else:
            seen.add(provider_id)
        source = provider.get("planned_source")
        if not isinstance(source, str) or source not in SOURCES:
            errors.append(f"{prefix}.planned_source is invalid")
        if provider.get("enabled") is not False:
            errors.append(f"{prefix}: collectors are not implemented; keep enabled=false")
        filters = provider.get("filters")
        if not isinstance(filters, dict):
            errors.append(f"{prefix}.filters must be an object")
            continue
        if set(filters) - FILTER_FIELDS:
            errors.append(f"{prefix}.filters contains unsupported fields")
        for name in FILTER_FIELDS & set(filters):
            value = filters[name]
            if not isinstance(value, list):
                errors.append(f"{prefix}.filters.{name} must be a list")
                continue
            if name == "gpu_counts":
                if any(type(item) is not int or item <= 0 for item in value):
                    errors.append(f"{prefix}.filters.gpu_counts must contain positive integers")
            elif any(not isinstance(item, str) or not item.strip() for item in value):
                errors.append(f"{prefix}.filters.{name} must contain non-empty strings")
            elif name in {"compute_countries", "sales_countries"}:
                if any(not re.fullmatch(r"[A-Z]{2}", item) for item in value):
                    errors.append(f"{prefix}.filters.{name} must use uppercase two-letter country codes")
            elif name == "currencies":
                if any(not re.fullmatch(r"[A-Z]{3}", item) for item in value):
                    errors.append(f"{prefix}.filters.currencies must use uppercase three-letter currency codes")
            elif name == "billing_modes" and any(item not in BILLING_MODES for item in value):
                errors.append(f"{prefix}.filters.billing_modes contains an unsupported mode")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GPU price collection library scaffold (no live collection yet)")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show scaffold status and non-secret environment options")
    validate = commands.add_parser("validate-config", help="check environment and collection configuration only")
    validate.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        print(f"Invalid environment configuration: {exc}", file=sys.stderr)
        return 1
    if args.command == "status":
        print(f"GPU Price Monitor {__version__}")
        print("Stage: collection library scaffold. Live provider adapters are not implemented.")
        print("Configured providers (not implemented): " + ", ".join(settings.providers))
        print(f"Request options: timeout={settings.timeout_seconds:g}s, max_retries={settings.max_retries}")
        print("Scope: fetch prices and return structured results. The calling application owns all other services.")
        return 0
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Cannot read configuration ({type(exc).__name__}).", file=sys.stderr)
        return 1
    errors = validate_config(config)
    if errors:
        for error in errors:
            print(f"Invalid configuration: {error}", file=sys.stderr)
        return 1
    print("Collection scaffold configuration and environment are valid. Provider access was not tested; no collection ran.")
    return 0
