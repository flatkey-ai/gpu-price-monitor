# GPU Price Monitor

**0.24.0: separate CSV schemas per provider.** Use `--format csv --csv-profile provider --output-dir exports/new-batch` to write one file per selected platform, with its own configuration columns. For a single provider, omit `--output-dir` to return CSV on stdout. Existing files are never overwritten. Headers are bilingual by default; exact member tariffs are preferred. Only eligible hourly prices with verified price locations are exported; empty files contain headers, never invented prices or worldwide scope.

Python: `prices_to_provider_csvs(result)` returns a provider-to-CSV-string mapping without file I/O, and `provider_csv_coverage(result)` explains omissions. Monetary amounts retain their original currencies; conversion belongs to the caller. The existing common `market`, `compact`, `catalog`, and `full` profiles remain available.

Vast.ai is now an optional anonymous offer collector (`--providers vast`, [scope](docs/vast.md)). It preserves specific machine configurations and explicit locations, but always reports partial coverage because pagination and market totals are not verified. `all` selects ten adapters, not all products in their markets.

**Version 0.23.0 adds RunPod datacenter starting rates and opt-in member-first CSV.**
RunPod uses anonymous official GraphQL queries without an API key or browser.
Secure and Community are cloud tiers, not membership levels. Complete mode keeps
datacenter minimum rates separate from unlocated catalog prices, with explicit
country evidence. See [RunPod](docs/runpod.md) and [configuration](.env.runpod.example).
Use `--format csv --prefer-member-prices` or `prices_to_csv(result, prefer_member=True)`
to prefer a verified AutoDL member price over the matching ordinary price for
the exact resource, configuration, region and capture. Eligibility remains labeled;
ambiguous matches are unchanged. JSON retains both tiers for audit. The flag is CSV-only.

Azure's anonymous Retail Prices API now covers 17 documented whole-GPU VM sizes
across T4, A10, A100, H100, MI300X and GB200. Exact hardware specifications and
regional retail rates are retained separately; fractional GPUs and undocumented
sizes are excluded. This is not an exhaustive Azure catalog. See [Azure scope](docs/azure.md).

**Version 0.22.0 fixes missing UCloud configuration quotes.** Small A800/H20
configurations now follow the official console's Normal-network rule; eight-GPU
configurations retain the enhanced mode. Explicitly empty P40 Singapore network
options use the console's Normal default. Catalog rows outside the current
account's zone directory, or sold-out rows without configurations, are reported
separately from collection failures. See [coverage](docs/DOCUMENT_COVERAGE.md).

Authenticated sources can run in a server or CI job with explicit valid credentials.
The library does not automate login or promise permanent cookies. Authentication
failures never silently fall back to public prices or historical snapshots.

**Version 0.21.0 adds public/account-visible Lambda reconciliation.** Select
`LAMBDA_SOURCE=visible` with `configured` or `api_preferred` to collect both the
official public price page and your own console catalogs. Every source observation
is retained separately; model, GPU count, CPU, memory, storage and rates are compared
without merging different configurations or borrowing geography. Record totals are
not deduplicated offer counts. Unpriced sales inquiries are excluded. See the
[configuration template](.env.lambda-visible.example) and [guide](docs/lambda-console.md).
`api_only` rejects this mixed HTML/API mode before collection.
In `visible` mode the default market CSV requires verified country/region
applicability; public offers without that evidence remain in JSON and the
catalog/full exports without borrowing locations from console offers.

The current coverage audit targets only official public and current-account-visible
GPU-hour rates, not unpublished sales or private contracts. Unknown geography is
not made globally uniform, and historical snapshots never replace a failed live
capture. UCloud errors now retain bounded official action/return codes for diagnosis
without exposing raw account responses.

Crusoe public collection now supports the official three-column CMS table,
validating model and rate alignment and failing on unexpected structure instead
of reusing historical prices.

**Version 0.20.0 adds UCloud UHost console-session collection**, for the GPU configuration product in the supplied document: set `UCLOUD_SOURCE=console` and `UCLOUD_SESSION_PATH`. It reads official country, region, zone and GPU configuration directories and requests hourly configuration quotes using standalone Python HTTP. Stock remains unknown by default; set `UCLOUD_CHECK_AVAILABILITY=true` for an additional inventory check. Collection needs no browser or LLM. UHost remains distinct from CompShare. The baseline prefers Base Linux images, falling back to an officially compatible preinstalled GPU Linux image only with a verified zero image fee. See the [session, scope and price guide](docs/ucloud-console.md).

Version 0.18 completes live verification of the Nebius account catalog.
`NEBIUS_SOURCE=catalog_api` discovers existing authorized projects and GPU presets,
then calls the official estimate API using your token; no manual targets are needed.
`spot_api` continues to read current regional Spot rates without authentication. Crusoe complete mode
reads every public GPU price cell alongside official VM specifications and deployment
locations. Deployment metadata is not a regional quote, sales-only amounts remain
empty, and no worldwide uniform price is inferred. See [usage and evidence](docs/nebius-crusoe.md),
[Nebius configuration](.env.nebius.example) and [Crusoe configuration](.env.crusoe.example).

The standalone Nebius account capture at **2026-10-22 14:21:49 Asia/Shanghai**
discovered and estimated 37 GPU presets, yielding **36 valid compute quotes across
nine regions in six countries**. GB300 returned a zero compute tariff and remains an
explicit `compute_tariff_unavailable` gap, not a free GPU offer; status is `partial`.
The main GPU-hour amount includes VM GPU/CPU/RAM. A 40 GiB SSD is estimated separately,
with disk cost and the full configuration total retained outside the comparison amount.
No resources or payment method were created. Coverage is limited to accessible account
projects, not all contracts or inventory; equal rates do not establish worldwide pricing.

The standalone Python capture at **2026-10-22 11:53 Asia/Shanghai** returned 12
original Nebius Spot rates across nine regions and six countries. Crusoe returned
seven numeric prices and 17 sales-only cells, alongside 17 documented GPU VM
configurations and seven deployment zones in three countries. Crusoe's price-region
binding remains unverified, so those catalog rates are excluded from the regional
comparison export. [Nebius CSV](examples/nebius-regional-spot-2026-10-22.csv),
[Crusoe price catalog](examples/crusoe-public-catalog-2026-10-22.csv),
[Crusoe deployment directory, not prices](examples/crusoe-deployment-catalog-2026-10-22.csv),
and [source diagnostics](examples/nebius-crusoe-sources-2026-10-22.json) are historical
samples, never runtime fallback data.

Version 0.16 adds explicit country/region applicability to `LAMBDA_SOURCE=console`.
For the same SKU, the listed selectable standard regions share one catalog rate;
the main CSV names their countries and regions without duplicating the quote or
claiming a nationwide rate. Every run checks the current official frontend version.
Changed code or insufficient evidence preserves JSON amounts with `partial` status
and excludes unverified applicability from the main CSV. Empty-capacity, dedicated
and unknown-location records remain in `catalog`, `full` and JSON. Collection is free,
requires no payment method or GPU launch, and uses no LLM. Cookies stay local. See
[setup and limitations](docs/lambda-console.md) and [environment template](.env.lambda.example).

The live capture at **2026-10-22 11:21:12 Asia/Shanghai** passed verification: 36 GPU
catalog records produced 19 main-CSV rows (five currently selectable on-demand
configurations and 14 cluster configurations). Seventeen records had no currently
selectable standard region. All selectable quotes in this batch were in the US;
the 18 platform-region metadata entries do not create quotes for other countries.
Inventory and row counts can change. Cluster duration and final purchase terms
remain unverified.

Version 0.14 adds `--catalog-scope complete` for Nebius, Lambda and Crusoe.
Copy `.env.three.example` to `.env.three.local` and pass `--env-file .env.three.local`.
The complete mode includes Nebius's explicit tariff/preset cost calculations and current
regional Spot rates, Lambda's on-demand and reserved cluster catalogs, and Crusoe's
numeric and sales-only public listings. Calculated configurations are marked as
derivations, not independent provider quotes. Nebius's account catalog and Lambda's
console-session HTTP path have now passed live verification; Lambda's API-key mode
and Crusoe contract authentication remain unverified. See the
[scope and authentication guide](docs/three-provider-coverage.md).

Use `--format csv --csv-profile catalog` for ten columns including labeled starting-price
and contact-sales entries (sales amounts stay blank). The default `market` export keeps
numeric hourly rates, `compact` requires verified country/region price evidence, and
`full` preserves audit metadata. Reserved clusters retain their commitment terms and
whole-cluster GPU counts. The library does not convert currencies or publish data.

A standalone GPU price collector for the five providers in the supplied document: **Nebius, Lambda, Crusoe, AutoDL, and UCloud**. Python and the CLI return JSON / CSV. Scheduling, storage, conversion, uploads, comparisons, and website publication belong to the calling application.

**0.19.0 adds direct AutoDL market JSON collection**, live-verified on 2026-10-22 with both Python and CLI `api_only`. A caller-exported minimal session reads explicit hourly ordinary/member tariffs without a browser or LLM: 3,372 market records, 3,279 GPU resources, 6,558 two-tier quotes, 30 models and 17 region codes. The 3,358 country-verified quotes qualify for `compact`; remaining country evidence gaps stay explicit. [Session export and usage](docs/autodl-market.md).

[中文](README.md) · [Provider evidence](docs/PROVIDERS.md) · [Data model](docs/DATA_MODEL.md) · [Document coverage](docs/DOCUMENT_COVERAGE.md)

**0.13.0 defaults to a ten-column `market` hourly price CSV** containing verified regional quotes and valid catalog quotes whose applicable region is not published. Catalog scope stays explicit; missing locations do not imply globally uniform pricing. Choose `compact` for verified country/region quotes only, or `full` for all source audit records.

The successful five-provider capture at **2026-10-21 17:45 Asia/Shanghai** returned 111 eligible hourly quotes: Nebius 17, Lambda 22, Crusoe 8, AutoDL 24 and UCloud CompShare 40. Of these, 52 have verified regions and 59 are catalog prices. [Captured CSV](examples/five-market-2026-10-21.csv) · [Source diagnostics](examples/five-market-sources-2026-10-21.json). Twenty starting-price/contact-sales records remain audit-only. No account keys were used; this is not complete configuration, region or inventory coverage.

## Clone and run the five providers

Requires Python 3.11+. No Codex, LLM, or model API key is needed. Public paths run without provider credentials; AutoDL's homepage path needs free local Chromium, while its authorized market JSON path needs no browser.

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser]'
python -m playwright install chromium
cp .env.five.example .env.five.local
gpu-price-monitor collect --env-file .env.five.local --pretty > prices.json
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
```

On Windows PowerShell use `py -3 -m venv .venv` and `.\.venv\Scripts\Activate.ps1`. Linux may require `python -m playwright install --with-deps chromium`. See [deployment](docs/DEPLOYMENT.md). This release is installed from source, not PyPI; check `gpu-price-monitor --version`.

```python
from pathlib import Path
from gpu_price_monitor import Settings, collect_prices, prices_to_csv

result = collect_prices(
    ["nebius", "lambda", "crusoe", "autodl", "ucloud"],
    settings=Settings(source_policy="api_preferred"),
)
print(result["status"], result["market_comparison"])
Path("prices.csv").write_text(prices_to_csv(result), encoding="utf-8", newline="")
```

Load a local profile explicitly with `Settings.from_env(env_file=".env.five.local")`. `Settings()` does not discover `.env` files. Process variables override file values, including empty values. Values are literal, without shell execution or interpolation.

## How each provider is collected

| Provider | `api_preferred` source | Limits |
| --- | --- | --- |
| Nebius | Default anonymous Spot API + website Next.js JSON; explicit `catalog_api` discovers account projects/presets and calls the official estimate API | Spot is region-bound; account compute rates include VM GPU/CPU/RAM, with SSD charged separately. Public starting prices and Contact us remain audit records |
| Lambda | Public page, keyed API, or explicit `console` mode with your own saved session | Instance cents are allocated over explicit GPU counts; the reviewed current frontend establishes one SKU catalog rate across its listed selectable standard regions, not independent regional quotes |
| Crusoe | Deterministic Python HTML parser for the GPU instances section | No verified public VM price API; billing, reservations, and managed model deployment prices are excluded |
| AutoDL | Direct authenticated market JSON in `market` mode; legacy homepage DOM in `public` mode | Market mode includes exact resource regions and ordinary/member hourly SKUs, with no browser dependency; homepage locations remain unknown |
| UCloud | Explicit `console` uses your saved session to discover UHost configurations and request prices; signed UHost targets and anonymous CompShare remain separate paths | Console quotes bind exact country, region, zone, GPU/CPU/RAM configuration and an explicit baseline network mode; account prices do not cover every contract, and CompShare does not replace UHost |

All amounts come from programmatic requests and fixed structures. No model interprets prices. Nebius website JSON is a website data endpoint, **not a documented stable cloud price API**: HTML supplies only the dynamic route, and the subsequent JSON supplies prices. UCloud frontend catalogs discover request configurations; actual quote responses supply amounts.

## CSV profiles

```bash
# Default market: valid GPU-hour catalog and regional quotes, ten columns.
gpu-price-monitor collect --env-file .env.five.local --format csv > prices.csv
# Verified country and price region only, ten columns.
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-profile compact > prices.regional.csv
# All source records, original 51-column audit schema.
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-profile full > prices.audit.csv
# Stable English headers for automated readers.
gpu-price-monitor collect --env-file .env.five.local --format csv --csv-headers english > prices.english.csv
```

The ten fields cover GPU/configuration, provider, quote applicability, native per-GPU amount, currency, unit, conditions, availability, source, and observation time. Headers are bilingual by default. Ordinary/member, Spot, tax, account conditions, source instance totals, and UCloud product line remain visible.

`market` and `compact` require numeric `quoted` GPU-hour rental rates. Starting prices, GPU-only components, monthly packages, contact-sales entries, discounts with unverified eligibility, and explicitly unavailable listings are excluded. `market` keeps valid catalogs with honest applicability labels; Lambda console shared-catalog records additionally need complete country/region details and currently selectable standard capacity. Other records remain in the full catalog. `compact` requires independently verified country/price-region evidence, so Lambda shared-catalog rates do not qualify. Unknown regions are never filled with global scope.

Python equivalents are `prices_to_csv(result)`, `prices_to_csv(result, profile="compact")`, and `prices_to_csv(result, profile="full")`. `market_eligible_quote` checks hourly catalog/regional eligibility; `publishable_quote` retains strict regional eligibility. Column constants are `MARKET_CSV_*`, `COMPACT_CSV_*`, and `CSV_*`.

Nebius `catalog_api` uses compute cost as its main amount, with
`instance_price.scope=compute_resources_only`. `storage_quote` retains the separately
estimated SSD fee and `full_configuration_price` retains the compute-plus-disk total.
CSV conditions explain these extras. Network and other unrequested services are excluded.

Amounts retain exact native decimal strings; **the library does not convert to USD** or divide monthly packages by 720. RackRate is a separate consumer. CSV has a UTF-8 BOM and CRLF endings; diagnostics stay on stderr. Keep JSON for provider status and exclusion details. Exit codes are `0` for successful sources, `2` for partial failure, and `1` for failure/configuration errors. A successful collection with no eligible rows in a profile produces a header-only CSV and still exits `0`.

## Source policies and credentials

| Policy | Behavior |
| --- | --- |
| `api_preferred` | Recommended five-provider policy; permits clearly labeled deterministic official-page and website-JSON sources where appropriate; selected API failures never trigger another source |
| `api_only` | Price APIs only; explicit AutoDL `market` and UCloud `console` are supported; public Nebius returns Spot, while explicit `catalog_api` / `api` allow account estimates, without website catalogs; Crusoe/AutoDL homepage sources fail with `api_price_source_unavailable` |
| `configured` | Backward-compatible default honoring `*_SOURCE`; public Nebius retains document + Spot, and public UCloud retains the older UHost monthly promotion adapter |

The five-provider profile sets `GPU_PRICE_MONITOR_PROVIDERS=nebius,lambda,crusoe,autodl,ucloud` and `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`. CLI `--providers` and `--source-policy` override them. The general `.env.example` retains `configured`.

| Optional capability | Required settings |
| --- | --- |
| Lambda authenticated catalog | `LAMBDA_API_KEY` + `LAMBDA_SOURCE=api`, or free session mode: `LAMBDA_SOURCE=console` + `LAMBDA_STORAGE_STATE_PATH` |
| UCloud UHost console catalog | Explicit `UCLOUD_SOURCE=console` + `UCLOUD_SESSION_PATH`; optional `UCLOUD_PROJECT_ID` and `UCLOUD_CHECK_AVAILABILITY`; no API key or manual targets; see the [guide](docs/ucloud-console.md) |
| Signed UCloud UHost quotes | `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY`, and one of `UCLOUD_PRICE_TARGETS_FILE` / `UCLOUD_PRICE_TARGETS_JSON`; optional `UCLOUD_PROJECT_ID` |
| Nebius account regional catalog | Explicit `NEBIUS_SOURCE=catalog_api` and `NEBIUS_ACCESS_TOKEN`; existing authorized projects/presets are discovered without targets; see [optional disk/currency settings](.env.nebius.example) |
| Nebius explicit configuration estimates | Explicit `NEBIUS_SOURCE=api`, `NEBIUS_ACCESS_TOKEN`, and one of `NEBIUS_PRICE_TARGETS_FILE` / `NEBIUS_PRICE_TARGETS_JSON`; the main amount totals all requested resources |
| Authorized AutoDL market | `AUTODL_SOURCE=market` and valid `AUTODL_STORAGE_STATE_PATH`; public homepage collection does not use a token |

Explicit UCloud `console` always selects the UHost session source: a missing or expired session fails rather than switching product lines. Signed API mode also rejects a partial key pair or missing targets. Target templates do not establish sellable configurations. Nebius `catalog_api`, Lambda's console-session mode and AutoDL market JSON passed standalone Python HTTP collection on 2026-10-22. Signed UCloud estimates, Lambda's API-key mode and Crusoe contract authentication still lack successful live credential verification; offline tests do not establish access. See [provider details](docs/PROVIDERS.md). Credentials, cookies, private targets, and browser state must not enter Git or price results.

JSON `execution` declares Python, deterministic rules, no LLM, and the policy. `provider_results` reports actual sources, collection methods, selection/fallback reasons, and per-provider `market_quote_count`. `market_comparison` counts eligible hourly catalog/regional quotes; the existing `comparison` retains strict regional counts. Successful collection, hourly-price eligibility, verified location, and current orderability are separate facts.

## Geographic evidence and scope

Country filters use ISO two-letter codes. Country/region/zone must match the same quote. For Lambda console, `--country` / `--region` match the reviewed shared-catalog applicability; combined conditions must match the same location entry, not an independently queried regional rate. JSON stores this scope separately in `price_applicability` / `applicable_*`. Capacity, platform coverage, currency, headquarters, and IP location alone do not establish price geography. Missing locations do not prove globally uniform rates. Documented coverage uses separate `--coverage-country` / `--coverage-region` filters. Unsupported dimensions return `unsupported_filter`; missing evidence for a supported dimension returns `unverifiable_filter`.

RunPod, DigitalOcean, Verda, and Azure adapters remain available through `--providers all`; the dedicated profile runs only the original five. [Archived examples](examples/README.md) are dated evidence and never runtime fallbacks. See [document coverage](docs/DOCUMENT_COVERAGE.md) for request, unit, location, and authentication boundaries.

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```
