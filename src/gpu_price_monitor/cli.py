"""Local project status and scaffold configuration checks. No network calls."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__

PROVIDERS = {"lambda", "nebius", "crusoe", "ucloud", "autodl"}
SOURCES = {"official_api", "public_documentation", "public_page", "official_quote_api", "authorized_browser"}


def validate_config(config: object) -> list[str]:
    """Check the current scaffold format, not runtime provider readiness."""
    errors: list[str] = []
    if not isinstance(config, dict):
        return ["configuration must be a JSON object"]
    if type(config.get("schema_version")) is not int or config["schema_version"] != 1:
        errors.append("schema_version must be 1")
    timezone = config.get("timezone")
    try:
        if not isinstance(timezone, str):
            raise ValueError
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        errors.append("timezone must be a valid IANA timezone")
    schedule = config.get("schedule")
    if not isinstance(schedule, dict):
        errors.append("schedule must be an object")
    else:
        for name in ("daily_at", "retry_at"):
            value = schedule.get(name)
            if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
                errors.append(f"schedule.{name} must use HH:MM")
        hours = schedule.get("stale_after_hours")
        if type(hours) is not int or hours <= 0:
            errors.append("schedule.stale_after_hours must be a positive integer")
    for section in ("notifications", "publication"):
        value = config.get(section)
        if not isinstance(value, dict) or type(value.get("enabled")) is not bool:
            errors.append(f"{section}.enabled must be a boolean")
        elif value["enabled"]:
            errors.append(f"{section} is not implemented; keep enabled=false")
    notifications = config.get("notifications", {})
    threshold = notifications.get("price_change_threshold_percent") if isinstance(notifications, dict) else None
    if type(threshold) not in (int, float) or not 0 < threshold <= 100:
        errors.append("notifications.price_change_threshold_percent must be in (0, 100]")
    publication = config.get("publication", {})
    if not isinstance(publication, dict) or publication.get("public_fields_only") is not True:
        errors.append("publication.public_fields_only must be true")
    providers = config.get("providers")
    if not isinstance(providers, list) or not providers:
        return errors + ["providers must be a non-empty list"]
    seen: set[str] = set()
    for index, provider in enumerate(providers):
        prefix = f"providers[{index}]"
        if not isinstance(provider, dict):
            errors.append(f"{prefix} must be an object")
            continue
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
        if provider.get("targets") != []:
            errors.append(f"{prefix}.targets must be empty until target schema and collectors are implemented")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GPU Price Monitor scaffold (no live collection)")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show project implementation status")
    validate = commands.add_parser("validate-config", help="check scaffold configuration only")
    validate.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "status":
        print(f"GPU Price Monitor {__version__}")
        print("Stage: project scaffold. Live collection, storage, dashboard and notifications are not implemented.")
        print("Providers: " + ", ".join(sorted(PROVIDERS)))
        print("Daily collection: not enabled. No provider credentials are read by this CLI.")
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
    print("Scaffold configuration is valid. No collectors or scheduled tasks were started.")
    return 0
