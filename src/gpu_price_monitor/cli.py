"""Python library CLI. Collection stdout contains only JSON."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .collector import IMPLEMENTED_PROVIDERS, PROVIDER_SOURCES, collect_prices
from .filters import normalize_filters
from .settings import ConfigurationError, PROVIDERS, SOURCES, Settings


def validate_config(config: object) -> list[str]:
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
            errors.append(f"{prefix}.id is not a known provider")
        elif provider_id in seen:
            errors.append(f"{prefix}.id is duplicated")
        else:
            seen.add(provider_id)
        source = provider.get("planned_source")
        if not isinstance(source, str) or source not in SOURCES:
            errors.append(f"{prefix}.planned_source is invalid")
        if type(provider.get("enabled")) is not bool:
            errors.append(f"{prefix}.enabled must be boolean")
        elif provider["enabled"]:
            if not isinstance(provider_id, str) or provider_id not in IMPLEMENTED_PROVIDERS:
                errors.append(f"{prefix}: provider adapter is not implemented; keep enabled=false")
            elif source != PROVIDER_SOURCES[provider_id]:
                errors.append(f"{prefix}.planned_source does not match the implemented adapter")
        try:
            if not isinstance(provider.get("filters"), dict):
                raise ConfigurationError("filters must be an object")
            normalize_filters(provider["filters"])
        except ConfigurationError as exc:
            errors.append(f"{prefix}: {exc}")
    return errors


def _load_config(path: Path) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError("Cannot read a valid JSON configuration file.") from None
    errors = validate_config(config)
    if errors:
        raise ConfigurationError("; ".join(errors))
    return config


def _print_json(result: dict, pretty: bool = False) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2 if pretty else None, allow_nan=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect GPU cloud prices and return JSON")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--env-file", type=Path, help="explicit dotenv file; process environment overrides its values")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="show implemented providers and non-secret environment options")
    validate = commands.add_parser("validate-config", help="check environment and configuration without making requests")
    validate.add_argument("--config", type=Path, required=True)
    collect = commands.add_parser("collect", help="fetch current public prices; stdout is JSON")
    for command in (status, validate, collect):
        command.add_argument("--env-file", type=Path, default=argparse.SUPPRESS,
                             help="explicit dotenv file; process environment overrides its values")
    collect.add_argument("--providers", "--provider", help="comma-separated provider names; defaults to ENV")
    collect.add_argument("--config", type=Path, help="collection configuration; only enabled providers may run")
    collect.add_argument("--pretty", action="store_true")
    collect.add_argument("--timeout", type=float, help="per-request timeout in seconds")
    collect.add_argument("--max-retries", type=int)
    options = {
        "gpu": "gpu_models", "region": "regions", "currency": "currencies",
        "billing-mode": "billing_modes", "country": "compute_countries",
        "sales-country": "sales_countries", "zone": "zones", "gpu-count": "gpu_counts",
    }
    for option, name in options.items():
        collect.add_argument(f"--{option}", dest=name, action="append", type=int if name == "gpu_counts" else str)
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env(env_file=args.env_file)
        if args.command == "status":
            print(f"GPU Price Monitor {__version__}")
            print("Available collectors: " + ", ".join(IMPLEMENTED_PROVIDERS))
            print("Providers not implemented: " + ", ".join(sorted(PROVIDERS - IMPLEMENTED_PROVIDERS.keys())))
            print("Configured providers: " + ", ".join(settings.providers))
            print(f"Request options: timeout={settings.timeout_seconds:g}s, max_retries={settings.max_retries}")
            print("No requests were made. Scheduling, storage and uploads belong to the caller.")
            return 0
        if args.command == "validate-config":
            _load_config(args.config)
            print("Collection configuration and environment are valid. Provider access was not tested; no collection ran.")
            return 0

        providers = None if args.providers is None else [p.strip().lower() for p in args.providers.split(",")]
        by_provider = None
        if args.config is not None:
            config = _load_config(args.config)
            settings = replace(settings, **config["request"])
            enabled = {p["id"]: p["filters"] for p in config["providers"] if p["enabled"]}
            if providers is None:
                providers = list(enabled)
            if any(p not in enabled for p in providers):
                raise ConfigurationError("Requested providers must be enabled in the configuration file.")
            by_provider = {p: enabled[p] for p in providers}
        overrides = {}
        if args.timeout is not None:
            overrides["timeout_seconds"] = args.timeout
        if args.max_retries is not None:
            overrides["max_retries"] = args.max_retries
        settings = replace(settings, **overrides)
        filters = {name: getattr(args, name) for name in options.values() if getattr(args, name) is not None}
        result = collect_prices(providers, filters, settings=settings, provider_filters=by_provider)
        _print_json(result, args.pretty)
        for provider in result["provider_results"]:
            if provider["error"]:
                print(f"{provider['provider']}: {provider['error']['code']}: {provider['error']['message']}", file=sys.stderr)
        return {"success": 0, "partial": 2, "failed": 1}[result["status"]]
    except ConfigurationError as exc:
        if args.command == "collect":
            _print_json({"schema_version": 1, "collected_at": datetime.now(timezone.utc).isoformat(), "status": "failed", "prices": [], "provider_results": [],
                         "error": {"code": "configuration_error", "message": str(exc), "retryable": False}}, args.pretty)
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 1
