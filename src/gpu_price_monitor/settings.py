"""Explicit environment configuration with no network access or global state."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from io import StringIO
from pathlib import Path

from dotenv.parser import parse_stream

PROVIDERS = frozenset({"lambda", "nebius", "crusoe", "ucloud", "autodl",
                       "runpod", "digitalocean", "verda", "azure", "vast"})
SOURCES = frozenset({
    "mixed_official_sources",
    "official_public_sources",
    "official_api", "public_documentation", "public_page",
    "official_quote_api", "official_public_api", "official_internal_api", "authorized_browser",
})
SOURCE_POLICIES = ("configured", "api_preferred", "api_only")
CATALOG_SCOPES = ("standard", "complete")


class ConfigurationError(ValueError):
    """Invalid configuration; messages do not include environment values."""


_MAX_ENV_BYTES = 256 * 1024
_TARGET_GROUPS = ({"UCLOUD_PRICE_TARGETS_JSON", "UCLOUD_PRICE_TARGETS_FILE"},
                  {"NEBIUS_PRICE_TARGETS_JSON", "NEBIUS_PRICE_TARGETS_FILE"})


def _read_text_file(path: Path, limit: int, error_message: str) -> str:
    """Read bounded UTF-8 input without exposing file paths or contents in errors."""
    try:
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except (OSError, UnicodeError, ValueError):
        raise ConfigurationError(error_message) from None
    if len(data) > limit:
        raise ConfigurationError(error_message)
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        raise ConfigurationError(error_message) from None


def _load_env_file(path: Path) -> dict[str, str]:
    raw = _read_text_file(path, _MAX_ENV_BYTES,
                          "Cannot read env file as UTF-8 within the 256 KiB limit.")
    values: dict[str, str] = {}
    # Parsing bindings directly avoids python-dotenv's warning logger, which can
    # include source details, and lets us reject partially parsed configuration.
    # No variable interpolation, shell evaluation or os.environ mutation occurs.
    for binding in parse_stream(StringIO(raw)):
        if binding.error:
            raise ConfigurationError("Env file contains invalid dotenv syntax.")
        if binding.key is not None:
            if binding.value is None or binding.key in values:
                raise ConfigurationError("Env file requires unique KEY=value assignments.")
            values[binding.key] = binding.value
    return values


@dataclass(frozen=True)
class Settings:
    """Per-call settings; never load files or contact providers on construction.

    Credential fields are hidden from repr and must not be serialized into
    collection results or logs. An API key is not proof of provider access.
    """

    providers: tuple[str, ...] = ("nebius", "crusoe")
    timeout_seconds: float = 30.0
    max_retries: int = 2
    lambda_api_key: str | None = field(default=None, repr=False)
    lambda_storage_state_path: str | None = field(default=None, repr=False)
    nebius_access_token: str | None = field(default=None, repr=False)
    crusoe_access_key_id: str | None = field(default=None, repr=False)
    crusoe_secret_key: str | None = field(default=None, repr=False)
    crusoe_organization_id: str | None = field(default=None, repr=False)
    ucloud_public_key: str | None = field(default=None, repr=False)
    ucloud_private_key: str | None = field(default=None, repr=False)
    ucloud_session_path: str | None = field(default=None, repr=False)
    ucloud_project_id: str | None = field(default=None, repr=False)
    ucloud_price_targets_json: str | None = field(default=None, repr=False)
    autodl_token: str | None = field(default=None, repr=False)
    autodl_storage_state_path: str | None = field(default=None, repr=False)
    ucloud_price_targets_file: str | None = field(default=None, repr=False)
    nebius_price_targets_json: str | None = field(default=None, repr=False)
    nebius_price_targets_file: str | None = field(default=None, repr=False)
    nebius_source: str = "public"
    nebius_catalog_boot_disk_gib: int = 40
    nebius_catalog_currency: str = "usd"
    lambda_source: str = "public"
    ucloud_source: str = "public"
    ucloud_check_availability: bool = False
    autodl_source: str = "public"
    crusoe_source: str = "public"
    source_policy: str = "configured"
    catalog_scope: str = "standard"

    def __post_init__(self) -> None:
        if not isinstance(self.providers, tuple) or not self.providers:
            raise ConfigurationError("providers must be a non-empty tuple")
        if any(not isinstance(item, str) or item not in PROVIDERS for item in self.providers):
            raise ConfigurationError("providers contains an unsupported provider")
        if len(set(self.providers)) != len(self.providers):
            raise ConfigurationError("providers must not contain duplicates")
        if (type(self.timeout_seconds) not in (int, float)
                or not 0 < self.timeout_seconds <= 300
                or not math.isfinite(self.timeout_seconds)):
            raise ConfigurationError("timeout_seconds must be finite and in (0, 300]")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 10:
            raise ConfigurationError("max_retries must be an integer in [0, 10]")
        if not isinstance(self.source_policy, str) or self.source_policy not in SOURCE_POLICIES:
            raise ConfigurationError("GPU_PRICE_MONITOR_SOURCE_POLICY must be configured, api_preferred or api_only")
        if not isinstance(self.catalog_scope, str) or self.catalog_scope not in CATALOG_SCOPES:
            raise ConfigurationError("GPU_PRICE_MONITOR_CATALOG_SCOPE must be standard or complete")
        if self.crusoe_source not in ("public", "account", "combined"):
            raise ConfigurationError("CRUSOE_SOURCE must be public, account or combined")
        if self.lambda_source not in ("public", "api", "console", "visible"):
            raise ConfigurationError("LAMBDA_SOURCE must be public, api, console or visible")
        if self.ucloud_source not in ("public", "api", "console"):
            raise ConfigurationError("UCLOUD_SOURCE must be public, api or console")
        if type(self.ucloud_check_availability) is not bool:
            raise ConfigurationError("UCLOUD_CHECK_AVAILABILITY must be true or false")
        if self.nebius_source not in ("public", "api", "catalog_api", "spot_api"):
            raise ConfigurationError("NEBIUS_SOURCE must be public, api, catalog_api or spot_api")
        if (type(self.nebius_catalog_boot_disk_gib) is not int
                or not 1 <= self.nebius_catalog_boot_disk_gib <= 32768):
            raise ConfigurationError("NEBIUS_CATALOG_BOOT_DISK_GIB must be an integer in [1, 32768]")
        if self.nebius_catalog_currency not in ("usd", "ils"):
            raise ConfigurationError("NEBIUS_CATALOG_CURRENCY must be usd or ils")
        if self.autodl_source not in ("public", "market"):
            raise ConfigurationError("AUTODL_SOURCE must be public or market")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *,
                 env_file: str | Path | None = None) -> Settings:
        """Read env with an optional, explicitly selected dotenv file.

        Process env (or the complete explicit mapping) overrides the file,
        including empty values. There is no file discovery, interpolation,
        environment mutation or network access. UCloud target files are read
        and validated here; relative paths use the env file's parent, or cwd.
        Direct Settings construction still performs no file I/O.
        """
        process_values = dict(os.environ if env is None else env)
        if any(not isinstance(key, str) or not isinstance(value, str)
               for key, value in process_values.items()):
            raise ConfigurationError("Environment names and values must be strings.")
        env_path = Path(env_file) if env_file is not None else None
        file_values = _load_env_file(env_path) if env_path is not None else {}
        values = {**file_values, **process_values}
        # JSON and FILE select the same target source. An explicitly supplied
        # process key selects that layer for both keys, even if its value is blank.
        for group in _TARGET_GROUPS:
            source_values = process_values if group & process_values.keys() else file_values
            for name in group:
                values.pop(name, None)
                if name in source_values:
                    values[name] = source_values[name]
        providers_value = values.get("GPU_PRICE_MONITOR_PROVIDERS", "nebius,crusoe")
        providers = tuple(item.strip().lower() for item in providers_value.split(","))
        try:
            timeout = float(values.get("GPU_PRICE_MONITOR_TIMEOUT_SECONDS", "30"))
        except ValueError:
            raise ConfigurationError("GPU_PRICE_MONITOR_TIMEOUT_SECONDS must be numeric") from None
        try:
            retries = int(values.get("GPU_PRICE_MONITOR_MAX_RETRIES", "2"))
        except ValueError:
            raise ConfigurationError("GPU_PRICE_MONITOR_MAX_RETRIES must be an integer") from None
        try:
            nebius_boot_disk = int(values.get("NEBIUS_CATALOG_BOOT_DISK_GIB", "40"))
        except ValueError:
            raise ConfigurationError("NEBIUS_CATALOG_BOOT_DISK_GIB must be an integer") from None

        def credential(name: str) -> str | None:
            value = values.get(name)
            return value if value and value.strip() else None

        ucloud_availability = values.get("UCLOUD_CHECK_AVAILABILITY", "false").lower()
        if ucloud_availability not in {"true", "false"}:
            raise ConfigurationError("UCLOUD_CHECK_AVAILABILITY must be true or false")

        targets_json = credential("UCLOUD_PRICE_TARGETS_JSON")
        targets_file = credential("UCLOUD_PRICE_TARGETS_FILE")
        if targets_json and targets_file:
            raise ConfigurationError("Set only one of UCLOUD_PRICE_TARGETS_JSON and UCLOUD_PRICE_TARGETS_FILE.")
        nebius_targets_json = credential("NEBIUS_PRICE_TARGETS_JSON")
        nebius_targets_file = credential("NEBIUS_PRICE_TARGETS_FILE")
        if nebius_targets_json and nebius_targets_file:
            raise ConfigurationError("Set only one of NEBIUS_PRICE_TARGETS_JSON and NEBIUS_PRICE_TARGETS_FILE.")
        settings = cls(
            providers=providers,
            timeout_seconds=timeout,
            max_retries=retries,
            lambda_api_key=credential("LAMBDA_API_KEY"),
            lambda_storage_state_path=credential("LAMBDA_STORAGE_STATE_PATH"),
            nebius_access_token=credential("NEBIUS_ACCESS_TOKEN"),
            crusoe_access_key_id=credential("CRUSOE_ACCESS_KEY_ID"),
            crusoe_secret_key=credential("CRUSOE_SECRET_KEY"),
            crusoe_organization_id=credential("CRUSOE_ORGANIZATION_ID"),
            ucloud_public_key=credential("UCLOUD_PUBLIC_KEY"),
            ucloud_private_key=credential("UCLOUD_PRIVATE_KEY"),
            ucloud_session_path=credential("UCLOUD_SESSION_PATH"),
            ucloud_project_id=credential("UCLOUD_PROJECT_ID"),
            ucloud_price_targets_json=targets_json,
            ucloud_price_targets_file=targets_file,
            nebius_price_targets_json=nebius_targets_json,
            nebius_price_targets_file=nebius_targets_file,
            autodl_token=credential("AUTODL_TOKEN"),
            autodl_storage_state_path=credential("AUTODL_STORAGE_STATE_PATH"),
            lambda_source=values.get("LAMBDA_SOURCE", "public"),
            ucloud_source=values.get("UCLOUD_SOURCE", "public"),
            ucloud_check_availability=ucloud_availability == "true",
            nebius_source=values.get("NEBIUS_SOURCE", "public"),
            nebius_catalog_boot_disk_gib=nebius_boot_disk,
            nebius_catalog_currency=values.get("NEBIUS_CATALOG_CURRENCY", "usd"),
            autodl_source=values.get("AUTODL_SOURCE", "public"),
            crusoe_source=values.get("CRUSOE_SOURCE", "public"),
            source_policy=values.get("GPU_PRICE_MONITOR_SOURCE_POLICY", "configured"),
            catalog_scope=values.get("GPU_PRICE_MONITOR_CATALOG_SCOPE", "standard"),
        )
        if settings.lambda_storage_state_path and env_path is not None:
            session_path = Path(settings.lambda_storage_state_path).expanduser()
            if not session_path.is_absolute():
                session_path = env_path.parent / session_path
            settings = replace(settings, lambda_storage_state_path=str(session_path))
        if settings.ucloud_session_path and env_path is not None:
            session_path = Path(settings.ucloud_session_path).expanduser()
            if not session_path.is_absolute():
                session_path = env_path.parent / session_path
            settings = replace(settings, ucloud_session_path=str(session_path))
        if targets_file:
            # Delayed imports keep Settings and provider modules independent at
            # import time; the target validator performs no authenticated calls.
            from .providers.ucloud import MAX_TARGET_JSON_BYTES, load_targets
            from .transport import FetchError

            target_path = Path(targets_file)
            if not target_path.is_absolute() and env_path is not None:
                target_path = env_path.parent / target_path
            raw_targets = _read_text_file(
                target_path, MAX_TARGET_JSON_BYTES,
                "Cannot read UCLOUD_PRICE_TARGETS_FILE as UTF-8 within the 128 KiB limit.",
            )
            settings = replace(settings, ucloud_price_targets_json=raw_targets)
            try:
                load_targets(settings)
            except FetchError:
                raise ConfigurationError("UCLOUD_PRICE_TARGETS_FILE must contain valid UCloud GPU quote targets.") from None
        if nebius_targets_file:
            from .providers.nebius_quote import MAX_TARGET_JSON_BYTES, load_targets
            from .transport import FetchError

            target_path = Path(nebius_targets_file)
            if not target_path.is_absolute() and env_path is not None:
                target_path = env_path.parent / target_path
            raw_targets = _read_text_file(target_path, MAX_TARGET_JSON_BYTES,
                                         "Cannot read NEBIUS_PRICE_TARGETS_FILE within the size limit.")
            settings = replace(settings, nebius_price_targets_json=raw_targets)
            try:
                load_targets(settings)
            except (FetchError, ValueError, KeyError, TypeError):
                raise ConfigurationError("NEBIUS_PRICE_TARGETS_FILE must contain valid Nebius GPU quote targets.") from None
        return settings
