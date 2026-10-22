# GPU Price Monitor

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
derivations, not independent provider quotes. Nebius account estimates, Lambda's
API-key mode and Crusoe contract authentication still lack successful live credential
verification; Lambda's console-session HTTP path has now passed it. See the
[scope and authentication guide](docs/three-provider-coverage.md).

Use `--format csv --csv-profile catalog` for ten columns including labeled starting-price
and contact-sales entries (sales amounts stay blank). The default `market` export keeps
numeric hourly rates, `compact` requires verified country/region price evidence, and
`full` preserves audit metadata. Reserved clusters retain their commitment terms and
whole-cluster GPU counts. The library does not convert currencies or publish data.

A standalone GPU price collector for the five providers in the supplied document: **Nebius, Lambda, Crusoe, AutoDL, and UCloud**. Python and the CLI return JSON / CSV. Scheduling, storage, conversion, uploads, comparisons, and website publication belong to the calling application.

[中文](README.md) · [Provider evidence](docs/PROVIDERS.md) · [Data model](docs/DATA_MODEL.md) · [Document coverage](docs/DOCUMENT_COVERAGE.md)

**0.13.0 defaults to a ten-column `market` hourly price CSV** containing verified regional quotes and valid catalog quotes whose applicable region is not published. Catalog scope stays explicit; missing locations do not imply globally uniform pricing. Choose `compact` for verified country/region quotes only, or `full` for all source audit records.

The successful five-provider capture at **2026-10-21 17:45 Asia/Shanghai** returned 111 eligible hourly quotes: Nebius 17, Lambda 22, Crusoe 8, AutoDL 24 and UCloud CompShare 40. Of these, 52 have verified regions and 59 are catalog prices. [Captured CSV](examples/five-market-2026-10-21.csv) · [Source diagnostics](examples/five-market-sources-2026-10-21.json). Twenty starting-price/contact-sales records remain audit-only. No account keys were used; this is not complete configuration, region or inventory coverage.

## Clone and run the five providers

Requires Python 3.11+. No Codex, LLM, or model API key is needed. Public paths run without provider credentials; AutoDL needs free local Chromium.

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
| Nebius | Anonymous current Spot API plus the official website Next.js JSON catalog | Spot is dynamic and region-bound; the catalog adds on-demand rates. L40S starting prices and Contact us remain audit records |
| Lambda | Public page, keyed API, or explicit `console` mode with your own saved session | Instance cents are allocated over explicit GPU counts; the reviewed current frontend establishes one SKU catalog rate across its listed selectable standard regions, not independent regional quotes |
| Crusoe | Deterministic Python HTML parser for the GPU instances section | No verified public VM price API; billing, reservations, and managed model deployment prices are excluded |
| AutoDL | Playwright with fixed DOM rules for ordinary/member prices | No suitable public market-price API; homepage locations are unknown; authorized market mode is optional |
| UCloud | Anonymous configuration-price API for its CompShare product line without keys; signed UHost configuration quotes with keys | Product lines remain distinct; ordinary list prices qualify, while discounts with unverified eligibility remain audit-only |

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

Amounts retain exact native decimal strings; **the library does not convert to USD** or divide monthly packages by 720. RackRate is a separate consumer. CSV has a UTF-8 BOM and CRLF endings; diagnostics stay on stderr. Keep JSON for provider status and exclusion details. Exit codes are `0` for successful sources, `2` for partial failure, and `1` for failure/configuration errors. A successful collection with no eligible rows in a profile produces a header-only CSV and still exits `0`.

## Source policies and credentials

| Policy | Behavior |
| --- | --- |
| `api_preferred` | Recommended five-provider policy; permits clearly labeled deterministic official-page and website-JSON sources where appropriate; selected API failures never trigger another source |
| `api_only` | Price APIs only; Nebius returns current Spot without website catalog; Crusoe/AutoDL page sources fail with `api_price_source_unavailable` |
| `configured` | Backward-compatible default honoring `*_SOURCE`; public Nebius retains document + Spot, and public UCloud retains the older UHost monthly promotion adapter |

The five-provider profile sets `GPU_PRICE_MONITOR_PROVIDERS=nebius,lambda,crusoe,autodl,ucloud` and `GPU_PRICE_MONITOR_SOURCE_POLICY=api_preferred`. CLI `--providers` and `--source-policy` override them. The general `.env.example` retains `configured`.

| Optional capability | Required settings |
| --- | --- |
| Lambda authenticated catalog | `LAMBDA_API_KEY` + `LAMBDA_SOURCE=api`, or free session mode: `LAMBDA_SOURCE=console` + `LAMBDA_STORAGE_STATE_PATH` |
| Signed UCloud UHost quotes | `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY`, and one of `UCLOUD_PRICE_TARGETS_FILE` / `UCLOUD_PRICE_TARGETS_JSON`; optional `UCLOUD_PROJECT_ID` |
| Nebius account estimates | Explicit `NEBIUS_SOURCE=api`, `NEBIUS_ACCESS_TOKEN`, and one of `NEBIUS_PRICE_TARGETS_FILE` / `NEBIUS_PRICE_TARGETS_JSON` |
| Authorized AutoDL market | `AUTODL_SOURCE=market` and valid `AUTODL_STORAGE_STATE_PATH`; public homepage collection does not use a token |

A partial UCloud key pair or missing account targets fails rather than falling back to another product line. Target templates do not establish sellable configurations. Lambda's console-session mode passed standalone Python HTTP collection on 2026-10-22. Nebius/UCloud account estimates, Lambda's API-key mode, Crusoe contract authentication and authorized AutoDL market still lack successful live credential verification; offline tests do not establish access. See [provider details](docs/PROVIDERS.md). Credentials, cookies, private targets, and browser state must not enter Git or price results.

JSON `execution` declares Python, deterministic rules, no LLM, and the policy. `provider_results` reports actual sources, collection methods, selection/fallback reasons, and per-provider `market_quote_count`. `market_comparison` counts eligible hourly catalog/regional quotes; the existing `comparison` retains strict regional counts. Successful collection, hourly-price eligibility, verified location, and current orderability are separate facts.

## Geographic evidence and scope

Country filters use ISO two-letter codes. Country/region/zone must match the same quote. For Lambda console, `--country` / `--region` match the reviewed shared-catalog applicability; combined conditions must match the same location entry, not an independently queried regional rate. JSON stores this scope separately in `price_applicability` / `applicable_*`. Capacity, platform coverage, currency, headquarters, and IP location alone do not establish price geography. Missing locations do not prove globally uniform rates. Documented coverage uses separate `--coverage-country` / `--coverage-region` filters. Unsupported dimensions return `unsupported_filter`; missing evidence for a supported dimension returns `unverifiable_filter`.

RunPod, DigitalOcean, Verda, and Azure adapters remain available through `--providers all`; the dedicated profile runs only the original five. [Archived examples](examples/README.md) are dated evidence and never runtime fallbacks. See [document coverage](docs/DOCUMENT_COVERAGE.md) for request, unit, location, and authentication boundaries.

```bash
python -m unittest discover -s tests -v
gpu-price-monitor validate-config --config configs/collect.all.example.json
```
