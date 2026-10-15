"""Explicit environment configuration with no network access or global state."""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

PROVIDERS = frozenset({"lambda", "nebius", "crusoe", "ucloud", "autodl"})
SOURCES = frozenset({
    "official_api", "public_documentation", "public_page",
    "official_quote_api", "authorized_browser",
})


class ConfigurationError(ValueError):
    """Invalid configuration; messages do not include environment values."""


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
    nebius_access_token: str | None = field(default=None, repr=False)
    ucloud_public_key: str | None = field(default=None, repr=False)
    ucloud_private_key: str | None = field(default=None, repr=False)
    autodl_token: str | None = field(default=None, repr=False)
    autodl_storage_state_path: str | None = field(default=None, repr=False)

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

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Read process env or an explicit mapping, without loading .env files.

        Does not resolve credential paths, test permissions or start collection.
        Calling applications load .env if desired. No env mutation is performed.
        """
        values = dict(os.environ if env is None else env)
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

        def credential(name: str) -> str | None:
            value = values.get(name)
            return value if value and value.strip() else None

        return cls(
            providers=providers,
            timeout_seconds=timeout,
            max_retries=retries,
            lambda_api_key=credential("LAMBDA_API_KEY"),
            nebius_access_token=credential("NEBIUS_ACCESS_TOKEN"),
            ucloud_public_key=credential("UCLOUD_PUBLIC_KEY"),
            ucloud_private_key=credential("UCLOUD_PRIVATE_KEY"),
            autodl_token=credential("AUTODL_TOKEN"),
            autodl_storage_state_path=credential("AUTODL_STORAGE_STATE_PATH"),
        )
