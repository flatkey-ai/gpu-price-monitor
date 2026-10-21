# GPU Price Monitor

An open-source library that collects GPU cloud rental prices from official sources and returns structured results through Python or a JSON CLI.

[中文](README.md) · [Plan](docs/PLAN.md) · [Data contract](docs/DATA_MODEL.md) · [Integration](docs/DEPLOYMENT.md) · [Roadmap](ROADMAP.md)

## Supported sources

Version 0.6.1 provides **11 free official public sources**: Nebius, Crusoe, Lambda, AutoDL, UCloud, RunPod, DigitalOcean, Verda, EBCloud, Suanli and Azure. Public collection needs no login, API keys, top-ups or payment card. Existing keys do not automatically select authenticated sources. Install from source; this version has not been published to PyPI.

Sources cover GPU instances, container rentals and explicitly advertised GPU compute rates while retaining each price's conditions. Add `--coverage` to inspect observed target models and gaps; this does not claim every provider, region or live inventory is covered. See the [11-provider capture](examples/all-providers-2026-10-20.json) and [mainstream model coverage](examples/mainstream-coverage-2026-10-20.json).

**Live capture on 2026-10-20 at 16:01 Asia/Shanghai: all 11 sources succeeded, returning 746 records (734 numeric prices and 12 contact-sales entries) and numeric listings for all 34 target model families, with zero gaps.** Coverage only indexes source records; member tariffs, component rates and offline promotions retain their conditions and do not establish stock or purchase eligibility, or coverage of every VRAM or hardware variant.

The Lambda public page was sampled on 2026-10-20: 22 rows across 4 tables for 8-, 4-, 2- and 1-GPU instances. Listed prices do not prove current capacity. The optional Lambda API and UCloud authenticated quotes have offline coverage, but no successful authenticated live pricing verification.

The library owns fetching, parsing, filter verification and structured results. Callers own scheduling, storage, history, uploads, comparisons, alerts and dashboards. No Flatkey upload endpoint is built in.

## Install and collect

Git, Python 3.11+ and network access to provider websites are required. No GPU is needed. Use an isolated virtual environment; public collection does not require an `.env` file.

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install '.[browser]'
python -m playwright install chromium
python -m gpu_price_monitor collect --providers all --coverage --lambda-source public --ucloud-source public --pretty
```

On Windows PowerShell, replace the virtual environment lines with `py -3 -m venv .venv` and `.\.venv\Scripts\Activate.ps1`; the remaining commands are the same. On a fresh Linux host or container, install Chromium's system dependencies with `python -m playwright install --with-deps chromium` (this may need administrator privileges). See [integration details](docs/DEPLOYMENT.md).

The installed `gpu-price-monitor` command is equivalent to `python -m gpu_price_monitor`. HTTP-only sources need just `python -m pip install .` and no Chromium; for example, `python -m gpu_price_monitor collect --providers nebius,lambda,runpod --pretty`.

The `collect` command writes JSON to stdout and diagnostics to stderr. Your application can capture the result or redirect stdout to a file.

```python
import json
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers="all",
    settings=Settings(),
    include_coverage=True,
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

The returned standard `dict` includes `schema_version`, `status`, UTC `collected_at`, `prices` and `provider_results`, plus `coverage` when requested. Successful quotes remain available if another provider fails. Each provider reports its status, applied filters and errors. See [data semantics](docs/DATA_MODEL.md).

[Free-route JSON snapshot from 2026-10-20](examples/lambda-autodl-2026-10-20.json): 46 records sampled at 14:55 Asia/Shanghai, comprising 22 Lambda records and 24 AutoDL records (12 ordinary, 12 member). Python and CLI collection both succeeded. This historical example is never a live fallback and does not establish inventory or authenticated API access.

## Filters and location limits

| Python filter | Repeatable CLI option | Current support |
| --- | --- | --- |
| `gpu_models` | `--gpu` | Applied to provider price records |
| `currencies` | `--currency` | Original USD / EUR / CNY currencies; no conversion |
| `billing_modes` | `--billing-mode` | Public UCloud packages are `monthly`; optional API is on-demand |
| `regions` | `--region` | Nebius, UCloud and Azure |
| `compute_countries`, `sales_countries` | `--country`, `--sales-country` | Filtering not enabled; public UCloud still retains official `country_code` metadata |
| `zones` | `--zone` | UCloud only |
| `gpu_counts` | `--gpu-count` | Lambda, UCloud, DigitalOcean, Verda, EBCloud and Azure |

For example, request a Nebius region with `gpu-price-monitor collect --providers nebius --region eu-north1 --pretty`. Unknown locations and card counts remain unknown. A supported configuration field does not imply that every provider can apply it.

## Configuration

```bash
gpu-price-monitor status
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

The standard example enables Nebius and Crusoe. `configs/collect.free.example.json` retains the Lambda, AutoDL and UCloud example; `configs/collect.all.example.json` enables all 11 sources. Without explicit providers or configuration, the default remains `nebius,crusoe`. Per-provider filters are supported; validation makes no network requests. Use `--timeout` and `--max-retries` for request options.

```bash
gpu-price-monitor collect --config configs/collect.free.example.json --lambda-source public --ucloud-source public --pretty
gpu-price-monitor collect --config configs/collect.all.example.json --coverage --lambda-source public --ucloud-source public --pretty
```

The 10 sources other than AutoDL need only the base `python3 -m pip install -e .`. AutoDL requires the optional browser dependency and Chromium installation above. New public sources have no required environment variables.

Use [`.env.example`](.env.example) as a reference. By default, settings read only the process environment. To load a local file, explicitly pass CLI `--env-file .env` or Python `Settings.from_env(env_file=".env")`. The library does not search parent directories, modify `os.environ`, interpolate variables or execute shell expressions from the file.

| Variable | Purpose / default |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | Comma-separated default providers; `nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | Timeout; `30` seconds |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | Maximum retries; `2` |
| `LAMBDA_SOURCE` | `public` by default; explicitly select `api` for the authenticated catalog |
| `LAMBDA_API_KEY` | Required only for `LAMBDA_SOURCE=api`; unused for public collection |
| `NEBIUS_ACCESS_TOKEN` | Reserved for authenticated estimates; not needed for current collection |
| `UCLOUD_SOURCE` | `public` by default; explicitly select `api` for authenticated quotes |
| `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY` | Required only for `UCLOUD_SOURCE=api` |
| `UCLOUD_PRICE_TARGETS_JSON` / `UCLOUD_PRICE_TARGETS_FILE` | API mode only: inline array or UTF-8 file, up to 20 complete targets |
| `UCLOUD_PROJECT_ID` | Optional UCloud project; subaccounts may require it |
| `AUTODL_TOKEN`, `AUTODL_STORAGE_STATE_PATH` | Reserved for authenticated features; unused by the free homepage route |

`collect` exit codes: `0` when every provider succeeds, including no matches; `2` for partial provider failure; `1` for total failure or invalid configuration. Check the JSON as well as the exit code.

## RunPod, DigitalOcean and Verda

```bash
gpu-price-monitor collect --providers runpod,digitalocean,verda --coverage --pretty
```

RunPod uses one anonymous read-only GraphQL query for GPU Pods catalog rates. `cloud_tier=secure` and `community` remain separate. Disabled-tier placeholder amounts, null/zero rates and MIG partitions are excluded. A per-GPU rate does not identify an instance GPU count, so `gpu_count` is unknown.

DigitalOcean parses its official on-demand and Spot GPU Droplet documentation, retaining instance totals for single- and explicitly labeled 8-GPU plans before allocating them per GPU. Spot rates are variable published snapshots. Verda retains the page's USD / EUR currencies and on-demand / Spot conditions without conversion.

These three pricing sources do not identify price regions or zones. Geography and stock remain unknown; capacity locations are not copied into price scope. See [provider details](docs/PROVIDERS.md).

## EBCloud, Suanli and Azure

```bash
gpu-price-monitor collect --providers ebcloud,suanli,azure --coverage --pretty
gpu-price-monitor collect --providers azure --region eastus --gpu T4 --pretty
```

EBCloud reads only the homepage's explicitly selected pay-as-you-go, one-GPU container configuration, retaining CPU and memory. Unselected multi-GPU and monthly options are not inferred. Suanli explicitly shares GPU card-hour pricing between cloud hosts and elastic service deployment; 18 GPU rates retain `pricing_product_scope`. NPUs and unverified accelerator types are excluded, and missing CPU/RAM resources remain unknown.

Azure uses the anonymous official Retail Prices API for two documented sizes only: T4 `Standard_NC4as_T4_v3` (1 GPU) and GB200 `Standard_ND128isr_NDR_GB200_v6` (4 GPUs). ARM region, on-demand / Spot conditions and instance totals remain explicit. Region and GPU-count filters are supported; zones and countries are not. Retail listings do not establish capacity or subscription eligibility.

## Free Lambda collection

The default source is [Lambda's official instances page](https://lambda.ai/instances); no `.env` or credentials are needed:

```bash
gpu-price-monitor collect --providers lambda --pretty
```

The published rate is per GPU-hour. The whole-instance hourly total is derived by multiplying it by GPU count; resource units remain GiB / TiB. Region, country and zone are unknown and cannot be used as verified price filters. Listings are not inventory.

## AutoDL coverage

The source is [AutoDL's public homepage](https://www.autodl.com/home). It exposes ordinary and member tariff cards; member prices retain their conditions and must not be treated as generally available ordinary prices.

The homepage does not provide per-machine regional quotes or live inventory. GPU count is unknown. Region, country, zone and card-count filters therefore return structured errors. Lambda and AutoDL have different currencies, so the shared example does not apply a USD-only filter.

## Free UCloud monthly packages

`UCLOUD_SOURCE=public` reads complete promotional packages for activities `10204` / `10216` / `10248` through anonymous website APIs. Region and zone IDs are checked against official public mappings:

```bash
gpu-price-monitor collect --providers ucloud --ucloud-source public --pretty
gpu-price-monitor collect --providers ucloud --region cn-bj2 --zone cn-bj2-02 --billing-mode monthly --pretty
```

The unit is `gpu_month`, with `instance_price.unit=instance_month`. Monthly prices are preserved and **never divided by 720**. Per-GPU values allocate a complete package, including CPU, RAM, disk and bandwidth.

These are conditional promotions, not standard on-demand market rates. Eligibility, purchase limits, renewal-discount information and offline flags remain part of the result. No offline flag is not proof of stock or purchase eligibility. See [provider research](docs/PROVIDERS.md).

The initial two-activity capture on 2026-10-20 returned 358 records. This [Beijing2 / Zone B / single T4S JSON](examples/ucloud-public-cn-bj2-2026-10-20.json) contains 18 filtered records sampled at 15:23 Asia/Shanghai, all marked `offline`. Adding the website-referenced `10248` activity expanded collection to 374 records, including 4090 48GB / 5090 packages, still all `offline`. Historical examples are never live fallbacks or inventory promises.

## Optional UCloud and Lambda API

Only explicit `UCLOUD_SOURCE=api` / `--ucloud-source api` uses UCloud keys and complete targets in local files excluded from Git. Lambda likewise uses its key only in explicit API mode. Authenticated UCloud example:

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=ucloud
UCLOUD_SOURCE=api
UCLOUD_PRICE_TARGETS_FILE=configs/ucloud-targets.local.json
```

Replace target locations and specifications with configurations you have checked. Inspect local settings without network access:

```bash
gpu-price-monitor status --env-file .env
```

After filling keys and confirming the targets, explicitly run live verification:

```bash
gpu-price-monitor collect --env-file .env --providers ucloud --ucloud-source api --pretty
```

Python uses `settings=Settings.from_env(env_file=".env")`. Relative target paths resolve against the env file directory, or the working directory without an env file. Process variables override file values, including empty strings. Nonempty JSON and FILE sources in the same layer conflict. See [integration details](docs/DEPLOYMENT.md).

The [target file](configs/ucloud-targets.example.json) is a format example, not proof of availability. UCloud targets require Region, Zone, GPU type/count, CPU, memory in MB and disk definitions. Only full GPU instances with `MachineType=G`, `ChargeType=Dynamic` and `Count=1` are supported. See [integration details](docs/DEPLOYMENT.md). Do not apply a shared USD-only filter to Lambda and UCloud, since UCloud returns CNY.

Missing credentials and inline JSON target errors return provider-level `missing_credentials`, `missing_price_targets` / `invalid_price_targets`, preserving other providers' results. FILE read or validation failures raise a global `ConfigurationError` before any provider starts collection.

## Price semantics and license

Keep original amounts, currencies, units, resources, sources and timestamps. Lambda public `amount` is its GPU-hour rate, with a derived instance total. UCloud promotions retain monthly prices and must not be compared directly with hourly rates. Public UCloud locations use official mappings; optional authenticated quotes retain requested locations without independent response verification. Component prices, starting prices, member tariffs and sales inquiries remain distinct. Listings do not guarantee availability.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before adding a provider. Only use read-only operations; do not create or buy resources to obtain a quote. [Apache-2.0](LICENSE) covers project code. Third-party data has separate usage and redistribution constraints; see [data policy](docs/DATA_POLICY.md).
