# GPU Price Monitor

A Python library and JSON / CSV CLI for **Nebius, Lambda, Crusoe, AutoDL, UCloud, RunPod, DigitalOcean, Verda, and Azure** GPU cloud prices. It collects, parses, filters, and returns quotes. Scheduling, persistence, currency conversion, uploads, comparisons, alerts, and dashboards belong to the calling application.

[中文](README.md) · [Document requirements and implementation](docs/DOCUMENT_COVERAGE.md) · [Provider details](docs/PROVIDERS.md) · [Environment template](.env.example)

The current **0.9.0** release adds CSV export. Version 0.8.0 added RunPod, DigitalOcean, Verda, and Azure to the original five-provider Word scope; `--providers all` still selects these nine providers. Dated examples retain their historical scope and do not establish complete market coverage. This version is installed from source and has not been published to PyPI. Run `gpu-price-monitor --version` after installation; CSV requires 0.9.0 or newer.

## What the locations mean

A public catalog does not necessarily publish a separate price for each country. The library does not infer a price location from headquarters, currency, IP address, capacity, or a platform's list of data centers, and does not copy one catalog price to every country.

| Provider | Free default | Geographic evidence |
| --- | --- | --- |
| Nebius | Official Compute pricing document, including USD / ILS and resource components | Public region labels describe platform coverage. Optional authenticated estimates verify the project region and official country mapping for a complete configuration |
| Lambda | Public instance page, retaining 1 / 2 / 4 / 8 GPU configurations | Public prices are not region-bound; API capacity locations are retained separately from price locations |
| Crusoe | The public GPU instances section | No region-specific prices in this table; Contact sales remains a nonnumeric quote |
| AutoDL | Public ordinary / member price cards | Homepage prices have no location. Optional authorized market collection preserves the market's region codes |
| UCloud | Anonymous official promotional packages and location catalogs | Packages are associated with their official country, region, and zone; optional configuration quotes require account keys and targets |
| RunPod | Anonymous official GraphQL GPU Pods catalog | Secure / Community tiers are separate; no price-bound regions are published in this catalog |
| DigitalOcean | Official GPU Droplet pricing document | Separate on-demand / Spot plans; full instance totals allocated across explicit 1 / 8 GPU counts; no price regions |
| Verda | Official USD / EUR GPU instances tables | Fetch each currency separately; retain on-demand / Spot and instance totals; no inferred compute countries |
| Azure | Anonymous official Retail Prices API | Already-effective regional rates for four verified SKUs only (T4, GB200, H100 NVL, and A100 PCIe); official region-directory country mappings; not all SKUs, countries, or capacity |

**Live public capture: October 21, 2026, 15:12:56 China time, 833 records across all nine sources.** Counts: Nebius 36, Crusoe 24, Lambda 22, UCloud 374, AutoDL 24, RunPod 68, DigitalOcean 19, Verda 52, and Azure 214. There are 574 country-bound records and 588 region/zone-bound records, including 374 offline UCloud packages; 36 have platform coverage only and 209 are unlocated catalogs. Azure covers 45 price regions, with 14 records retaining unknown countries. These counts do not establish currently purchasable capacity everywhere. See the [actual JSON](examples/nine-providers-2026-10-21.json); the original Word-scope [five-provider capture](examples/five-providers-2026-10-21.json) is retained separately.

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

On Windows PowerShell use `py -3 -m venv .venv` and `.\.venv\Scripts\Activate.ps1`. On Linux, missing browser libraries may require `python -m playwright install --with-deps chromium`. For HTTP-only collection install `python -m pip install .` and select `--providers nebius,lambda,crusoe,ucloud,runpod,digitalocean,verda,azure`.

Stdout contains JSON by default, or CSV with `collect --format csv`; diagnostics go to stderr. Exit codes: `0` for success, including valid filters with no matches; `2` for partial failure; `1` for failure or invalid configuration. A failed source does not return zero prices or an archived snapshot.

```python
from gpu_price_monitor import Settings, collect_prices

result = collect_prices("all", settings=Settings(), include_coverage=True)
for quote in result["prices"]:
    print(quote["provider"], quote["gpu_model"], quote["amount"],
          quote["currency"], quote["unit"], quote["price_scope"],
          quote["compute_countries"], quote["regions"], quote["zones"])
```

## Export a CSV table

**New in 0.9.0:** `prices_to_csv(result)` and `collect --format csv`. JSON remains the default; the Python `collect_prices` result, existing JSON CLI, and exit codes remain compatible. CSV text is generated with the Python standard library, with no spreadsheet dependency. The library does not write files, upload results, or convert currencies.

```bash
# Default JSON preserves per-provider status and coverage summaries.
gpu-price-monitor collect --providers all --coverage --pretty > prices.json

# CSV goes to stdout; the shell writes the file and stderr keeps diagnostics.
gpu-price-monitor collect --providers all --format csv > prices.csv
```

```python
from pathlib import Path
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices("all", settings=Settings())
csv_text = prices_to_csv(result)
# The returned text already contains a BOM and CRLF line endings.
Path("prices.csv").write_text(csv_text, encoding="utf-8", newline="")
```

Each CSV row represents one filtered quote, preserving the GPU model and provider, original amount / currency / period, instance total, country / region / zone, geographic evidence scope, ordinary / member and cloud-tier conditions, Spot, offline status, source, and observation time. Unknown locations stay empty or explicitly unlocated; platform coverage does not become a regional price. CNY / EUR / ILS remain in their original currencies and monthly amounts stay monthly. RackRate separately handles USD presentation, storage, and website updates.

The output uses a **UTF-8 BOM** and **CRLF** line endings. CSV contains only the quote table, with no `provider_results`, `geographic_coverage`, or model `coverage` appendix. Use JSON for the complete summaries, even when `--coverage` is supplied. Partial failure exits `2`; complete failure or invalid configuration exits `1`; diagnostics go to stderr. CSV contains successful-source quotes, or only its header when none are returned. A file's existence is not proof of success: check the exit code or retain the JSON status.

## Country, region, and zone filters

Countries use ISO two-letter codes. A combined country / region / zone selection must describe the same quote, rather than matching unrelated entries. Unsupported dimensions return `unsupported_filter`. A supported dimension without the required source evidence returns `unverifiable_filter` rather than silently accepting an unverified location.

```bash
# Public monthly packages: retain offline status and the original monthly unit.
gpu-price-monitor collect --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --pretty

# Azure meters bind ARM regions; countries use verified official-directory mappings.
gpu-price-monitor collect --providers azure --gpu T4 --country US --region eastus --pretty

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

Deployment countries and sales jurisdictions differ; `sales_countries` is unsupported. `geographic_coverage` summarizes location evidence for the returned quotes. `price_scope` distinguishes `unlocated_catalog`, `platform_coverage`, `regional_quote`, `zone_quote`, `requested_region_quote`, and `requested_zone_quote`. Neither field guarantees capacity or purchase eligibility. Azure has some regions without verified country mappings. A country-only request can therefore return `unverifiable_filter`; combine it with an evidenced region, such as US + eastus above, rather than silently excluding records with unknown countries.

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
| All nine public sources | No mandatory environment variables; switchable sources retain `*_SOURCE=public`; the four added adapters use anonymous public sources only |
| Nebius configuration estimate | `NEBIUS_SOURCE=api`, `NEBIUS_ACCESS_TOKEN`, and `NEBIUS_PRICE_TARGETS_FILE` or `NEBIUS_PRICE_TARGETS_JSON` |
| Lambda authenticated catalog | `LAMBDA_SOURCE=api`, `LAMBDA_API_KEY`; capacity regions do not become regional rates |
| UCloud configuration quote | `UCLOUD_SOURCE=api`, `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY`, and `UCLOUD_PRICE_TARGETS_FILE` or `UCLOUD_PRICE_TARGETS_JSON`; optional `UCLOUD_PROJECT_ID` |
| AutoDL regional market | `AUTODL_SOURCE=market`, `AUTODL_STORAGE_STATE_PATH`; invalid sessions fail without falling back to homepage prices |

Targets are configuration templates, not verified sellable offers. Nebius estimates require a real project, a supported platform / preset and GPU count, and complete storage specifications. The adapter verifies the project's region using a read-only request and checks the official country mapping. Hour and month estimates retain their returned aggregation unit; month aggregation does not mean a monthly rental commitment. Contract estimates remain account-specific.

UCloud targets specify a whole hourly GPU host, including region, zone, GPU, CPU, memory, and disks. Official location catalogs are loaded on API collection to validate location and country. The private key stays client-side for signing. Authentication and private resource identifiers are not written to price results.

To prepare your own authorized AutoDL session, run `python -m playwright codegen --save-storage=playwright/.auth/autodl.storage-state.json https://www.autodl.com/market/list`, log in manually, close the window, and set that path in the environment file. Session files, `.env`, and `*.local.json` are Git-ignored and must not be shared. `AUTODL_TOKEN` is reserved and is not used by either current AutoDL mode.

RunPod Secure Cloud and Community Cloud are distinct cloud tiers, not ordinary/member identities; `cloud_tier` and `conditions.cloud_type` preserve them. DigitalOcean and Verda retain complete `instance_price` totals and allocate them over explicit GPU counts. Verda USD / EUR prices are separately fetched original-currency lists, not currency conversions. Azure currently covers only four fixed, verified SKUs. Keep ordinary, member, contract, component, promotional, starting, contact-sales, and offline quotes distinct. The library preserves source currency, units, resources, discounts, effective dates when published, and observation time. It does not convert to USD or divide monthly prices by an assumed 720 hours. RackRate is a separate consumer with its own conversion, scheduling, and publishing logic.

## Verification

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```

Offline fixtures validate parsing and failure behavior, not live account access. Nebius's new quote adapter has 14 synthetic tests; AutoDL's authorized market adapter has eight. The dated public captures are evidence of their observation time and are never used as runtime fallbacks.
