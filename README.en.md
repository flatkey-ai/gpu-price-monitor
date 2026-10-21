# GPU Price Monitor

A Python library and JSON / CSV CLI for **Nebius, Lambda, Crusoe, AutoDL, UCloud, RunPod, DigitalOcean, Verda, and Azure** GPU cloud prices. It collects, parses, filters, and returns quotes. Scheduling, persistence, currency conversion, uploads, comparisons, alerts, and dashboards belong to the calling application.

[中文](README.md) · [Document requirements and implementation](docs/DOCUMENT_COVERAGE.md) · [Provider details](docs/PROVIDERS.md) · [Environment template](.env.example)

The current **0.12.0** release adds source policies. For the five providers in the supplied document, use `--providers nebius,lambda,crusoe,autodl,ucloud --source-policy api_preferred`: use suitable APIs when available, select public pages under explicit rules when an API or credentials are missing, and report the actual source. Collection runs in standalone Python, without Codex, an LLM, a model API key, or manual page interpretation. Crusoe and AutoDL public prices still require deterministic page rules; this is not an API-only implementation for all five providers.

CSV still defaults to a strict **10-column regional GPU-hour comparison table**. Only actual numeric hourly quotes with verified countries and regions are included. Use `--csv-profile full` for the original 51-column source audit table. Both profiles retain bilingual headers by default, with an English-only option. `--providers all` selects all nine providers above. Install from source and check `gpu-price-monitor --version`; this version has not been published to PyPI.

## What the locations mean

A public catalog does not necessarily publish a separate price for each country. The library does not infer a price location from headquarters, currency, IP address, capacity, or a platform's list of data centers, and does not copy one catalog price to every country. Missing region fields do not establish globally uniform pricing; no such claim is made without explicit official evidence.

| Provider | Source under `api_preferred` | Geographic evidence |
| --- | --- | --- |
| Nebius | Public mode calls only the anonymous current Spot API; explicit `api` retains authenticated configuration estimates | Spot entries bind a platform, region, currency and effective time; countries use the official region directory; no Compute-document fetch is needed |
| Lambda | Instance API with `LAMBDA_API_KEY`; deterministic public-page parsing without a key | Public prices are not region-bound; API capacity locations remain separate; 1 / 2 / 4 / 8 GPU configurations are retained |
| Crusoe | Deterministic parsing of the official GPU instances section; no verified public VM price API found | No region-specific prices in this table; Contact sales stays nonnumeric; billing and managed inference are excluded |
| AutoDL | Playwright with fixed DOM rules for ordinary/member cards; explicit `market` retains the authorized market mode | Homepage prices have no location; market region codes are retained; existing-resource Pro APIs are not market catalogs |
| UCloud | Account quote API when either account key is configured; anonymous promotional API otherwise | Account quotes require both keys and targets; anonymous regional monthly packages do not become hourly rates |
| RunPod | Anonymous official GraphQL GPU Pods catalog | Secure / Community tiers are separate; no price-bound regions are published in this catalog |
| DigitalOcean | Official GPU Droplet pricing document | Separate on-demand / Spot plans; full instance totals allocated across explicit 1 / 8 GPU counts; no price regions |
| Verda | Official USD / EUR GPU instances tables | Fetch each currency separately; retain on-demand / Spot and instance totals; no inferred compute countries |
| Azure | Anonymous official Retail Prices API | Already-effective regional rates for four verified SKUs only (T4, GB200, H100 NVL, and A100 PCIe); official region-directory country mappings; not all SKUs, countries, or capacity |

The five-provider 0.12.0 run completed at **2026-10-21 17:18:56 Asia/Shanghai**, with all sources successful: Nebius 12, Lambda 22, Crusoe 24, AutoDL 24 and UCloud 374 source records. The [actual source report](examples/five-api-preferred-sources-2026-10-21.json) preserves execution policy and adapter diagnostics. Without account keys, Lambda used its public page and UCloud returned monthly promotional packages; only the 12 Nebius regional Spot quotes qualified for the strict hourly CSV. This does not establish five-provider regional hourly coverage.

**The 0.11.0 public capture at 2026-10-21T08:45:38.349457Z contained 845 source records and 224 eligible regional GPU-hour quotes**: 12 Nebius current Spot entries and 212 Azure entries. See the [224-row, native-currency comparison CSV](examples/regional-hourly-2026-10-21.csv). The other seven sources in that capture lacked complete price locations or provided offline monthly packages, so they contributed no eligible comparison rows. This does not establish that those providers have no purchasable products or verify successful authenticated collection in 0.12.0.

The [833-record nine-provider JSON](examples/nine-providers-2026-10-21.json) and [five-provider JSON](examples/five-providers-2026-10-21.json) are historical audit captures. They include unlocated catalogs, platform coverage, contact-sales entries and offline monthly packages; they are not the current comparison table. Use `comparison.eligible_quote_count` for the current eligible count.

The supplied Nebius chart showed B200 at **4.10 in me-west1 and 1.90 USD/GPU/hour in us-central1 at 2026-10-21 08:00 UTC**. Those are historical Spot last-price points, not ordinary on-demand rates or fixed current prices. The API observation at 08:45:03 UTC was already **3.8 / 1.6** for those respective regions. Current collection reads the [official anonymous Spot endpoint](https://docs.nebius.com/signup-billing/spot-prices), preserving its effective time; screenshot values and historical chart aggregates are never hardcoded as live prices.

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
python -m gpu_price_monitor collect --providers nebius,lambda,crusoe,autodl,ucloud --source-policy api_preferred --pretty
```

On Windows PowerShell use `py -3 -m venv .venv` and `.\.venv\Scripts\Activate.ps1`. On Linux, missing browser libraries may require `python -m playwright install --with-deps chromium`. For HTTP-only collection install `python -m pip install .` and select `--providers nebius,lambda,crusoe,ucloud,runpod,digitalocean,verda,azure`.

Stdout contains JSON by default, or CSV with `collect --format csv`; diagnostics go to stderr. Exit codes: `0` for success, including valid filters with no matches; `2` for partial failure; `1` for failure or invalid configuration. A failed source does not return zero prices or an archived snapshot.

```python
from gpu_price_monitor import Settings, collect_prices

result = collect_prices(
    ["nebius", "lambda", "crusoe", "autodl", "ucloud"],
    settings=Settings(source_policy="api_preferred"),
    include_coverage=True,
)
for quote in result["prices"]:
    print(quote["provider"], quote["gpu_model"], quote["amount"],
          quote["currency"], quote["unit"], quote["price_scope"],
          quote["compute_countries"], quote["regions"], quote["zones"])
```

## Source policies and execution evidence

| Policy | Behavior |
| --- | --- |
| `configured` | Backward-compatible default: honor each `*_SOURCE` setting; the presence of a key alone does not enable an account API |
| `api_preferred` | Recommended for the original five: public Nebius uses only Spot API; Lambda uses its API with a key or the public page without one; any UCloud key requires complete account-quote configuration, otherwise use anonymous promotional APIs; Crusoe and AutoDL use clearly labeled page rules |
| `api_only` | Permit price APIs only; page sources such as Crusoe and AutoDL fail with `api_price_source_unavailable`, without page fallback; missing Lambda keys or incomplete account configuration also fail |

Use `Settings(source_policy="api_preferred")`, CLI `--source-policy api_preferred`, or `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred` loaded through `Settings.from_env()` or explicit `--env-file`. An explicitly selected account API fails on authentication errors, request errors, or changed response formats; it does not fall back to a public page or an archived sample.

JSON `execution` declares `runtime=python`, `parsing=deterministic_rules`, `uses_llm=false`, and the selected `source_policy`. Each `provider_results` entry reports its actual `source_type`, `collection_method`, `selection_reason`, and applicable `fallback_reason`. Methods are `http_json`, `http_html`, `http_document`, or `browser_dom`; the compatible Nebius document/API combination is labeled `hybrid_http`. API preference does not relabel a page parser as an API.

Collecting source records from five providers does **not** establish complete regional hourly comparison prices from all five. Lambda capacity locations are not price regions. Anonymous UCloud monthly packages are not converted to hourly rates. Unlocated Crusoe and AutoDL homepage records remain excluded from the default comparison CSV.

## Export a CSV table

Since **0.11.0**, `prices_to_csv(result)` and `collect --format csv` default to ten columns: GPU model/configuration, provider, price country/region, native per-GPU amount, currency, unit, pricing conditions, availability, official source, and observation time. Ordinary/member, cloud-tier, Spot, tax and account conditions remain visible. Instance totals are included only when the source provides them.

The comparison profile requires a numeric `quoted` amount, `unit=gpu_hour`, a verified regional price scope, and nonempty country and region evidence. Unlocated records, platform coverage, starting prices, GPU components, monthly packages, contact-sales entries and explicitly unavailable/offline listings are excluded. `prices_to_csv(result, profile="full")` or `--csv-profile full` preserves the original 51-column audit table and all source records. JSON remains the default full source result. The library returns text without writing files, uploading results, or converting currencies.

```bash
# Default JSON preserves per-provider status and coverage summaries.
gpu-price-monitor collect --providers all --coverage --pretty > prices.json

# Default strict 10-column comparison; stderr reports included/excluded counts.
gpu-price-monitor collect --providers all --format csv > prices.csv
# Stable English field names for automated readers.
gpu-price-monitor collect --providers all --format csv --csv-headers english > prices.english.csv
# All source records in the compatible 51-column audit profile.
gpu-price-monitor collect --providers all --format csv --csv-profile full > prices.audit.csv
```

```python
from pathlib import Path
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices("all", settings=Settings())
csv_text = prices_to_csv(result)  # Strict 10 columns, bilingual headers by default
english_csv_text = prices_to_csv(result, bilingual_headers=False)
audit_csv_text = prices_to_csv(result, profile="full")
# The returned text already contains a BOM and CRLF line endings.
Path("prices.csv").write_text(csv_text, encoding="utf-8", newline="")
```

`--csv-profile compact` explicitly selects the default comparison table; `full` selects the audit table. `COMPACT_CSV_COLUMNS` / `COMPACT_CSV_HEADERS` define the ten comparison columns, while `CSV_COLUMNS` / `CSV_HEADERS` retain the 51-column schema. Older consumers requiring that schema must select `full`. `publishable_quote(quote)` checks comparison eligibility. `--csv-headers english` or `bilingual_headers=False` changes only the selected profile's header IDs.

Amounts retain exact native decimal strings; CNY / EUR / ILS are not converted to USD. Monthly records remain in JSON / full audit output and are never divided by 720 or any assumed number of hours. Unknown locations are not filled with global scope, and platform coverage never creates country prices. RackRate separately handles conversion, storage and publication.

Output uses a **UTF-8 BOM** and **CRLF** line endings. Observation and effective timestamps retain their original ISO representation. CSV has no provider-status or coverage appendix; use JSON for the full result. The default comparison writes an inclusion/exclusion count to stderr. Successful source collection with no eligible quotes produces a header-only CSV and still exits `0`; partial source failure exits `2`, and complete failure or invalid configuration exits `1`. Keep JSON or full audit output when investigating excluded records.

## Country, region, and zone filters

Countries use ISO two-letter codes. A combined country / region / zone selection must describe the same quote, rather than matching unrelated entries. Unsupported dimensions return `unsupported_filter`. A supported dimension without the required source evidence returns `unverifiable_filter` rather than silently accepting an unverified location.

```bash
# Public monthly packages: retain offline status and the original monthly unit.
gpu-price-monitor collect --providers ucloud --country CN --region cn-bj2 --zone cn-bj2-02 --pretty

# Azure meters bind ARM regions; countries use verified official-directory mappings.
gpu-price-monitor collect --providers azure --gpu T4 --country US --region eastus --pretty

# Current Nebius regional Spot prices; country/region refer to actual price locations.
gpu-price-monitor collect --providers nebius --gpu B200 --billing-mode spot --country US --region us-central1 --pretty

# Documented platform coverage is queried separately from price locations.
gpu-price-monitor collect --providers nebius --coverage-region eu-north1 --coverage-country FI --pretty

# Optional authenticated paths, after completing local credentials and targets.
gpu-price-monitor collect --env-file .env --providers nebius --nebius-source api --country FI --region eu-north1 --pretty
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --country CN --region cn-bj2 --pretty

# Authorized AutoDL market session; use region codes actually returned by it.
gpu-price-monitor collect --env-file .env --providers autodl --autodl-source market --pretty
```

Python filters accept arrays under `compute_countries`, `regions`, `zones`, `gpu_models`, `gpu_counts`, `currencies`, `billing_modes`, `coverage_regions`, and `coverage_countries`. For example:

```python
result = collect_prices(
    ["ucloud"],
    {"compute_countries": ["CN"], "regions": ["cn-bj2"]},
    settings=Settings(),
)
```

`--country` / `--region` match only actual price locations. Use `--coverage-country` / `--coverage-region` for documented Nebius platform coverage, usually in a separate request. Coverage does not populate price `compute_countries` / `regions`. Deployment countries and sales jurisdictions differ; `sales_countries` is unsupported. `geographic_coverage` summarizes location evidence for the returned quotes. `price_scope` distinguishes `unlocated_catalog`, `platform_coverage`, `regional_quote`, `zone_quote`, `requested_region_quote`, and `requested_zone_quote`. Neither field guarantees capacity or purchase eligibility. Azure has some regions without verified country mappings. A country-only request can therefore return `unverifiable_filter`; combine it with an evidenced region, such as US + eastus above, rather than silently excluding records with unknown countries.

## Optional account configuration

Use the dedicated five-provider profile to keep an existing `.env` separate:

```bash
cp .env.five.example .env.five.local
gpu-price-monitor collect --env-file .env.five.local --providers nebius,lambda,crusoe,autodl,ucloud --pretty
```

It sets `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`. Empty keys use public paths; completed Lambda/UCloud credentials select account APIs under the policy. A lone UCloud key or missing targets is a configuration error, not a successful hourly quote. The general template below retains `configured` for compatibility:

```bash
cp .env.example .env
cp configs/nebius-targets.example.json configs/nebius-targets.local.json
cp configs/ucloud-targets.example.json configs/ucloud-targets.local.json
gpu-price-monitor status --env-file .env
```

Load `.env` explicitly with `--env-file .env` or `Settings.from_env(env_file=".env")`. Process values override file values, including empty values. Values are literal: no shell execution, interpolation, or automatic file discovery. Constructing `Settings()` performs no credential-file reads.

| Mode | Required configuration |
| --- | --- |
| All nine public sources | No mandatory environment variables; `configured` retains `*_SOURCE=public`; use `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred` for the recommended five-provider run |
| Nebius configuration estimate | `NEBIUS_SOURCE=api`, `NEBIUS_ACCESS_TOKEN`, and `NEBIUS_PRICE_TARGETS_FILE` or `NEBIUS_PRICE_TARGETS_JSON` |
| Lambda authenticated catalog | `LAMBDA_API_KEY`, with `api_preferred` or explicit `LAMBDA_SOURCE=api`; capacity regions do not become regional rates |
| UCloud configuration quote | `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY`, and `UCLOUD_PRICE_TARGETS_FILE` or `UCLOUD_PRICE_TARGETS_JSON`, with `api_preferred` or explicit `UCLOUD_SOURCE=api`; optional `UCLOUD_PROJECT_ID` |
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

Offline fixtures validate parsing and failure behavior, not live account access. The anonymous current Nebius Spot source has a live public capture; optional account estimates and the authorized AutoDL market still require successful live-account verification. The dated public captures are evidence of their observation time and are never used as runtime fallbacks.
