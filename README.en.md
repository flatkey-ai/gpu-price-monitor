# GPU Price Monitor

A Python library and JSON CLI for **Nebius, Lambda, Crusoe, AutoDL, and UCloud** GPU cloud prices. It collects, parses, filters, and returns quotes. Scheduling, persistence, currency conversion, uploads, comparisons, alerts, and dashboards belong to the calling application.

[中文](README.md) · [Document requirements and implementation](docs/DOCUMENT_COVERAGE.md) · [Provider details](docs/PROVIDERS.md) · [Environment template](.env.example)

Starting with **0.7.0**, these five providers are the entire supported scope; `--providers all` selects exactly these five. Other adapters have been removed. Dated examples from older versions retain their historical scope. This version is installed from source and has not been published to PyPI.

## What the locations mean

A public catalog does not necessarily publish a separate price for each country. The library does not infer a price location from headquarters, currency, IP address, capacity, or a platform's list of data centers, and does not copy one catalog price to every country.

| Provider | Free default | Geographic evidence |
| --- | --- | --- |
| Nebius | Official Compute pricing document, including USD / ILS and resource components | Public region labels describe platform coverage. Optional authenticated estimates verify the project region and official country mapping for a complete configuration |
| Lambda | Public instance page, retaining 1 / 2 / 4 / 8 GPU configurations | Public prices are not region-bound; API capacity locations are retained separately from price locations |
| Crusoe | The public GPU instances section | No region-specific prices in this table; Contact sales remains a nonnumeric quote |
| AutoDL | Public ordinary / member price cards | Homepage prices have no location. Optional authorized market collection preserves the market's region codes |
| UCloud | Anonymous official promotional packages and location catalogs | Packages are associated with their official country, region, and zone; optional configuration quotes require account keys and targets |

**Live public capture: October 21, 2026, 14:35 China time, 480 records.** Nebius returned 36, Crusoe 24, Lambda 22, AutoDL 24, and UCloud 374. All 374 UCloud monthly packages were marked offline in China. The 36 Nebius entries indicate platform coverage; the remaining 70 catalog entries have no price location. This is not evidence of currently purchasable prices in every country. See the [actual JSON](examples/five-providers-2026-10-21.json).

The collectors use read-only public requests, authenticated estimates, or an authorized market session; they do not create, launch, or purchase resources. Optional authenticated paths have offline tests but have not been successfully verified with a valid live account. Documentation examples and synthetic fixtures are not live API results.

## Clone and run

Requirements: Python 3.11+, Git, and network access to the official sources. Public collection requires no keys or `.env`; AutoDL requires Playwright and the free local Chromium browser.

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser]'
python -m playwright install chromium
python -m gpu_price_monitor collect --providers all --coverage --pretty
```

On Windows PowerShell use `py -3 -m venv .venv` and `.\.venv\Scripts\Activate.ps1`. On Linux, missing browser libraries may require `python -m playwright install --with-deps chromium`. For HTTP-only collection install `python -m pip install .` and select `--providers nebius,lambda,crusoe,ucloud`.

Stdout contains JSON; diagnostics go to stderr. Exit codes: `0` for success, including valid filters with no matches; `2` for partial failure; `1` for failure or invalid configuration. A failed source does not return zero prices or an archived snapshot.

```python
from gpu_price_monitor import Settings, collect_prices

result = collect_prices("all", settings=Settings(), include_coverage=True)
for quote in result["prices"]:
    print(quote["provider"], quote["gpu_model"], quote["amount"],
          quote["currency"], quote["unit"], quote["price_scope"],
          quote["compute_countries"], quote["regions"], quote["zones"])
```

## Country, region, and zone filters

Countries use ISO two-letter codes. A combined country / region / zone selection must describe the same quote, rather than matching unrelated entries. Unsupported dimensions return `unsupported_filter`. A supported dimension without the required source evidence returns `unverifiable_filter` rather than silently accepting an unverified location.

```bash
# Public monthly packages: retain offline status and the original monthly unit.
gpu-price-monitor collect --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --pretty

# Public Nebius region labels indicate platform coverage, not a regional quote.
gpu-price-monitor collect --providers nebius --region eu-north1 --currency USD --pretty

# Optional authenticated paths, after completing local credentials and targets.
gpu-price-monitor collect --env-file .env --providers nebius --nebius-source api --country FI --region eu-north1 --pretty
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --country CN --region cn-bj2 --pretty

# Authorized AutoDL market session; use region codes actually returned by it.
gpu-price-monitor collect --env-file .env --providers autodl --autodl-source market --pretty
```

Python filters accept arrays under `compute_countries`, `regions`, `zones`, `gpu_models`, `gpu_counts`, `currencies`, and `billing_modes`. For example:

```python
result = collect_prices(
    ["ucloud"],
    {"compute_countries": ["CN"], "regions": ["cn-bj2"]},
    settings=Settings(),
)
```

Deployment countries and sales jurisdictions differ; `sales_countries` is unsupported. `geographic_coverage` summarizes location evidence for the returned quotes. `price_scope` distinguishes `unlocated_catalog`, `platform_coverage`, `regional_quote`, `zone_quote`, `requested_region_quote`, and `requested_zone_quote`. Neither field guarantees capacity or purchase eligibility.

## Optional account configuration

```bash
cp .env.example .env
cp configs/nebius-targets.example.json configs/nebius-targets.local.json
cp configs/ucloud-targets.example.json configs/ucloud-targets.local.json
gpu-price-monitor status --env-file .env
```

Load `.env` explicitly with `--env-file .env` or `Settings.from_env(env_file=".env")`. Process values override file values, including empty values. Values are literal: no shell execution, interpolation, or automatic file discovery. Constructing `Settings()` performs no credential-file reads.

| Mode | Required configuration |
| --- | --- |
| All five public sources | No mandatory environment variables; `*_SOURCE=public` |
| Nebius configuration estimate | `NEBIUS_SOURCE=api`, `NEBIUS_ACCESS_TOKEN`, and `NEBIUS_PRICE_TARGETS_FILE` or `NEBIUS_PRICE_TARGETS_JSON` |
| Lambda authenticated catalog | `LAMBDA_SOURCE=api`, `LAMBDA_API_KEY`; capacity regions do not become regional rates |
| UCloud configuration quote | `UCLOUD_SOURCE=api`, `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY`, and `UCLOUD_PRICE_TARGETS_FILE` or `UCLOUD_PRICE_TARGETS_JSON`; optional `UCLOUD_PROJECT_ID` |
| AutoDL regional market | `AUTODL_SOURCE=market`, `AUTODL_STORAGE_STATE_PATH`; invalid sessions fail without falling back to homepage prices |

Targets are configuration templates, not verified sellable offers. Nebius estimates require a real project, a supported platform / preset and GPU count, and complete storage specifications. The adapter verifies the project's region using a read-only request and checks the official country mapping. Hour and month estimates retain their returned aggregation unit; month aggregation does not mean a monthly rental commitment. Contract estimates remain account-specific.

UCloud targets specify a whole hourly GPU host, including region, zone, GPU, CPU, memory, and disks. Official location catalogs are loaded on API collection to validate location and country. The private key stays client-side for signing. Authentication and private resource identifiers are not written to price results.

To prepare your own authorized AutoDL session, run `python -m playwright codegen --save-storage=playwright/.auth/autodl.storage-state.json https://www.autodl.com/market/list`, log in manually, close the window, and set that path in the environment file. Session files, `.env`, and `*.local.json` are Git-ignored and must not be shared. `AUTODL_TOKEN` is reserved and is not used by either current AutoDL mode.

Keep ordinary, member, contract, component, promotional, starting, contact-sales, and offline quotes distinct. The library preserves source currency, units, resources, discounts, effective dates when published, and observation time. It does not convert to USD or divide monthly prices by an assumed 720 hours. RackRate is a separate consumer with its own conversion, scheduling, and publishing logic.

## Verification

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

Offline fixtures validate parsing and failure behavior, not live account access. Nebius's new quote adapter has 14 synthetic tests; AutoDL's authorized market adapter has eight. The dated public captures are evidence of their observation time and are never used as runtime fallbacks.
