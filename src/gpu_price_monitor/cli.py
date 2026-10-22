"""Python library CLI. Collection stdout contains only the selected data format."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .collector import IMPLEMENTED_PROVIDERS, collect_prices, provider_source
from .csv_export import market_eligible_quote, prices_to_csv, publishable_quote
from .filters import normalize_filters
from .settings import CATALOG_SCOPES, ConfigurationError, PROVIDERS, SOURCE_POLICIES, SOURCES, Settings


def validate_config(config: object, *, settings: Settings | None = None) -> list[str]:
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
            elif source != provider_source(provider_id, settings):
                errors.append(f"{prefix}.planned_source does not match the implemented adapter")
        try:
            if not isinstance(provider.get("filters"), dict):
                raise ConfigurationError("filters must be an object")
            normalize_filters(provider["filters"])
        except ConfigurationError as exc:
            errors.append(f"{prefix}: {exc}")
    return errors


def _load_config(path: Path, settings: Settings | None = None) -> dict:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError("Cannot read a valid JSON configuration file.") from None
    errors = validate_config(config, settings=settings)
    if errors:
        raise ConfigurationError("; ".join(errors))
    return config


def _print_json(result: dict, pretty: bool = False) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2 if pretty else None, allow_nan=False))


def _print_collection(result: dict, output_format: str, pretty: bool = False, *, csv_headers: str = "bilingual",
                      csv_profile: str = "market") -> None:
    if output_format == "csv":
        # Keep the promised encoding and CRLF bytes when redirected on Windows.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", newline="")
        sys.stdout.write(prices_to_csv(result, bilingual_headers=csv_headers == "bilingual", profile=csv_profile))
    else:
        _print_json(result, pretty)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect GPU cloud prices and return JSON or CSV")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--env-file", type=Path, help="explicit dotenv file; process environment overrides its values")
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="show implemented providers and non-secret environment options")
    validate = commands.add_parser("validate-config", help="check environment and configuration without making requests")
    validate.add_argument("--config", type=Path, required=True)
    collect = commands.add_parser("collect", help="fetch current public prices; stdout is JSON or CSV")
    login = commands.add_parser("lambda-login", help="manually sign in using a new browser and save a private Lambda session")
    login.add_argument("--state-file", required=True, type=Path, help="new private session file; existing files are never overwritten")
    login.add_argument("--timeout", type=int, default=300, help="manual login timeout, 1–300 seconds (default: 300)")
    for command in (status, validate, collect):
        command.add_argument("--env-file", type=Path, default=argparse.SUPPRESS,
                             help="explicit dotenv file; process environment overrides its values")
        command.add_argument("--source-policy", choices=SOURCE_POLICIES, default=None,
                             help="configured sources (default), prefer available APIs, or require APIs only")
        command.add_argument("--catalog-scope", choices=CATALOG_SCOPES, default=None,
                             help="standard (default), or complete: include official tariff calculations and reserved conditions; account and sales-only gaps remain")
    collect.add_argument("--providers", "--provider", help="comma-separated provider names, or all; defaults to ENV")
    collect.add_argument("--config", type=Path, help="collection configuration; only enabled providers may run")
    collect.add_argument("--format", choices=("json", "csv"), default="json",
                         help="stdout format (default: json); csv is UTF-8 with a BOM")
    collect.add_argument("--csv-headers", choices=("bilingual", "english"), default="bilingual",
                         help="CSV header labels: English identifiers with Chinese translations (default), or English only")
    collect.add_argument("--csv-profile", choices=("market", "catalog", "compact", "full"), default="market",
                         help="market: numeric GPU-hour quotes (default); catalog: hourly listings including floors and contact sales; compact: verified regional quotes only; full: all records for audit")
    collect.add_argument("--pretty", action="store_true", help="indent JSON output; ignored for CSV")
    collect.add_argument("--coverage", action="store_true", help="include GPU family coverage in JSON output")
    collect.add_argument("--timeout", type=float, help="per-request timeout in seconds")
    collect.add_argument("--max-retries", type=int)
    collect.add_argument("--lambda-source", choices=("public", "api", "console"),
                         help="Lambda public page, keyed API, or read-only console JSON using your own saved login session")
    collect.add_argument("--ucloud-source", choices=("public", "api"),
                         help="UCloud source; public promotional packages are free to read, api requires keys and targets")
    collect.add_argument("--nebius-source", choices=("public", "api"),
                         help="Nebius public tariff or explicit authenticated regional configuration estimate")
    collect.add_argument("--autodl-source", choices=("public", "market"),
                         help="AutoDL public tariff or regional market using an explicitly supplied saved session")
    collect.add_argument("--crusoe-source", choices=("public", "account", "combined"),
                         help="Crusoe public prices, read-only account contract audit, or both; account audit requires credentials")
    options = {
        "gpu": "gpu_models", "region": "regions", "currency": "currencies",
        "billing-mode": "billing_modes", "country": "compute_countries",
        "sales-country": "sales_countries", "zone": "zones", "gpu-count": "gpu_counts",
        "coverage-region": "coverage_regions", "coverage-country": "coverage_countries",
    }
    for option, name in options.items():
        collect.add_argument(f"--{option}", dest=name, action="append", type=int if name == "gpu_counts" else str)
    args = parser.parse_args(argv)
    try:
        if args.command == "lambda-login":
            from .lambda_login import save_lambda_session
            from .transport import FetchError
            if not 1 <= args.timeout <= 300:
                raise ConfigurationError("Login timeout must be between 1 and 300 seconds.")
            try:
                save_lambda_session(args.state_file, timeout_seconds=args.timeout)
            except FetchError as exc:
                print(f"Lambda login: {exc.code}: {exc}", file=sys.stderr)
                return 1
            print("Lambda session saved privately. Select LAMBDA_SOURCE=console and set LAMBDA_STORAGE_STATE_PATH to this file.")
            return 0
        settings = Settings.from_env(env_file=args.env_file)
        if args.source_policy is not None:
            settings = replace(settings, source_policy=args.source_policy)
        if args.catalog_scope is not None:
            settings = replace(settings, catalog_scope=args.catalog_scope)
        if getattr(args, "lambda_source", None) is not None:
            settings = replace(settings, lambda_source=args.lambda_source)
        if getattr(args, "ucloud_source", None) is not None:
            settings = replace(settings, ucloud_source=args.ucloud_source)
        if getattr(args, "nebius_source", None) is not None:
            settings = replace(settings, nebius_source=args.nebius_source)
        if getattr(args, "autodl_source", None) is not None:
            settings = replace(settings, autodl_source=args.autodl_source)
        if getattr(args, "crusoe_source", None) is not None:
            settings = replace(settings, crusoe_source=args.crusoe_source)
        if args.command == "status":
            print(f"GPU Price Monitor {__version__}")
            print("Available collectors: " + ", ".join(IMPLEMENTED_PROVIDERS))
            print("Providers not implemented: " + (", ".join(sorted(PROVIDERS - IMPLEMENTED_PROVIDERS.keys())) or "none"))
            print("Configured providers: " + ", ".join(settings.providers))
            print("Source policy: " + settings.source_policy)
            print("Catalog scope: " + settings.catalog_scope)
            for provider in settings.providers:
                print(f"{provider} source type: {provider_source(provider, settings)}")
            print("Lambda source: " + settings.lambda_source)
            print("UCloud source: " + settings.ucloud_source)
            print("Nebius source: " + settings.nebius_source)
            print("AutoDL source: " + settings.autodl_source)
            print("Crusoe source: " + settings.crusoe_source)
            if settings.catalog_scope == "complete":
                print("Complete mode includes official tariff calculations and reserved conditions; account-specific and sales-only prices may remain unavailable.")
            print(f"Request options: timeout={settings.timeout_seconds:g}s, max_retries={settings.max_retries}")
            print("No requests were made. Scheduling, storage and uploads belong to the caller.")
            return 0
        if args.command == "validate-config":
            _load_config(args.config, settings)
            print("Collection configuration and environment are valid. Provider access was not tested; no collection ran.")
            return 0

        select_all = args.providers is not None and args.providers.strip().lower() == "all"
        providers = None if args.providers is None or select_all else [p.strip().lower() for p in args.providers.split(",")]
        by_provider = None
        if args.config is not None:
            config = _load_config(args.config, settings)
            settings = replace(settings, **config["request"])
            enabled = {p["id"]: p["filters"] for p in config["providers"] if p["enabled"]}
            if providers is None:
                providers = list(enabled)
            if any(p not in enabled for p in providers):
                raise ConfigurationError("Requested providers must be enabled in the configuration file.")
            by_provider = {p: enabled[p] for p in providers}
        elif select_all:
            providers = list(IMPLEMENTED_PROVIDERS)
        overrides = {}
        if args.timeout is not None:
            overrides["timeout_seconds"] = args.timeout
        if args.max_retries is not None:
            overrides["max_retries"] = args.max_retries
        settings = replace(settings, **overrides)
        filters = {name: getattr(args, name) for name in options.values() if getattr(args, name) is not None}
        result = collect_prices(providers, filters, settings=settings, provider_filters=by_provider,
                                include_coverage=args.coverage)
        _print_collection(result, args.format, args.pretty, csv_headers=args.csv_headers, csv_profile=args.csv_profile)
        if settings.catalog_scope == "complete":
            print("Complete mode includes official tariff calculations and reserved conditions. "
                  "Inspect provider coverage and gaps; account-specific and sales-only prices may remain unavailable.", file=sys.stderr)
        if args.format == "csv" and args.csv_profile == "market":
            kept = sum(market_eligible_quote(q) for q in result["prices"])
            regional = sum(publishable_quote(q) for q in result["prices"] if market_eligible_quote(q))
            print(f"CSV market: {kept} numeric GPU-hour quotes ({regional} verified regional, "
                  f"{kept - regional} catalog); {len(result['prices']) - kept} records excluded. "
                  "Catalog prices do not establish regional or globally uniform pricing. "
                  "Use --csv-profile compact for regional quotes, full for audit.", file=sys.stderr)
        if args.format == "csv" and args.csv_profile == "compact":
            kept = sum(publishable_quote(q) for q in result["prices"])
            print(f"CSV comparison: {kept} verified regional GPU-hour quotes; "
                  f"{len(result['prices']) - kept} collected records excluded. Use JSON or --csv-profile full for audit.", file=sys.stderr)
        for provider in result["provider_results"]:
            if provider["error"]:
                print(f"{provider['provider']}: {provider['error']['code']}: {provider['error']['message']}", file=sys.stderr)
        return {"success": 0, "partial": 2, "failed": 1}[result["status"]]
    except ConfigurationError as exc:
        if args.command == "collect":
            _print_collection({"schema_version": 1, "collected_at": datetime.now(timezone.utc).isoformat(), "status": "failed", "prices": [], "provider_results": [],
                               "error": {"code": "configuration_error", "message": str(exc), "retryable": False}}, args.format, args.pretty,
                              csv_headers=args.csv_headers, csv_profile=args.csv_profile)
        print(f"Invalid configuration: {exc}", file=sys.stderr)
        return 1
