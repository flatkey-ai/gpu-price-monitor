# GPU Price Monitor

[Free-route JSON snapshot from 2026-10-20](examples/lambda-autodl-2026-10-20.json): 46 records sampled at 14:55 Asia/Shanghai, comprising 22 Lambda records and 24 AutoDL records (12 ordinary, 12 member). Python and CLI collection both succeeded. This historical example is never a live fallback and does not establish inventory or authenticated API access.

An open-source library that collects GPU cloud rental prices from official sources and returns structured results through Python or a JSON CLI.

[中文](README.md) · [Plan](docs/PLAN.md) · [Data contract](docs/DATA_MODEL.md) · [Integration](docs/DEPLOYMENT.md) · [Roadmap](ROADMAP.md)

## Supported sources

Version 0.4.0 provides **free public Lambda and AutoDL price collection** without login, API keys, top-ups or a payment card. Lambda defaults to its public instances page; AutoDL reads ordinary and member tariffs from its public homepage in a fresh unauthenticated browser context. Existing keys, tokens or saved login state are not used for these paths. Nebius and Crusoe remain public sources; UCloud is an optional authenticated quote source. Install from source; this version has not been published to PyPI.

The Lambda public page was sampled on 2026-10-20: 22 rows across 4 tables for 8-, 4-, 2- and 1-GPU instances. Listed prices do not prove current capacity. The optional Lambda API and UCloud authenticated quotes have offline coverage, but no successful authenticated live pricing verification.

The library owns fetching, parsing, filter verification and structured results. Callers own scheduling, storage, history, uploads, comparisons, alerts and dashboards. No Flatkey upload endpoint is built in.

## Install and collect

Python 3.11+ is required. No GPU is needed.

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m pip install -e '.[browser]'
python3 -m playwright install chromium
gpu-price-monitor collect --providers lambda,autodl --lambda-source public --pretty
```

The `collect` command writes JSON to stdout and diagnostics to stderr. Your application can capture the result or redirect stdout to a file.

```python
import json
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers=["lambda", "autodl"],
    settings=Settings(lambda_source="public"),
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

The returned standard `dict` includes `schema_version`, `status`, UTC `collected_at`, `prices` and `provider_results`. Successful quotes remain available if another provider fails. Each provider reports its status, applied filters and errors. See [data semantics](docs/DATA_MODEL.md).

## Filters and location limits

| Python filter | Repeatable CLI option | Current support |
| --- | --- | --- |
| `gpu_models` | `--gpu` | Applied to provider price records |
| `currencies` | `--currency` | Lambda USD; AutoDL / UCloud CNY; no conversion |
| `billing_modes` | `--billing-mode` | According to explicit source terms; UCloud Dynamic only |
| `regions` | `--region` | Nebius and UCloud only; Lambda / AutoDL / Crusoe unsupported |
| `compute_countries`, `sales_countries` | `--country`, `--sales-country` | No reliable mapping in current providers; structured error |
| `zones` | `--zone` | UCloud only |
| `gpu_counts` | `--gpu-count` | Lambda and UCloud only |

For example, request a Nebius region with `gpu-price-monitor collect --providers nebius --region eu-north1 --pretty`. Unknown locations and card counts remain unknown. A supported configuration field does not imply that every provider can apply it.

## Configuration

```bash
gpu-price-monitor status
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

The standard example enables Nebius and Crusoe. `configs/collect.free.example.json` enables Lambda and AutoDL. Without explicit providers or configuration, the default remains `nebius,crusoe`. Per-provider filters are supported; validation makes no network requests. Use `--timeout` and `--max-retries` for request options.

```bash
gpu-price-monitor collect --config configs/collect.free.example.json --pretty
```

For HTTP-only sources, a base `python3 -m pip install -e .` is sufficient. AutoDL requires the optional browser dependency and Chromium installation above.

Use [`.env.example`](.env.example) as a reference. By default, settings read only the process environment. To load a local file, explicitly pass CLI `--env-file .env` or Python `Settings.from_env(env_file=".env")`. The library does not search parent directories, modify `os.environ`, interpolate variables or execute shell expressions from the file.

| Variable | Purpose / default |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | Comma-separated default providers; `nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | Timeout; `30` seconds |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | Maximum retries; `2` |
| `LAMBDA_SOURCE` | `public` by default; explicitly select `api` for the authenticated catalog |
| `LAMBDA_API_KEY` | Required only for `LAMBDA_SOURCE=api`; unused for public collection |
| `NEBIUS_ACCESS_TOKEN` | Reserved for authenticated estimates; not needed for current collection |
| `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY` | Required for UCloud account quotations |
| `UCLOUD_PRICE_TARGETS_JSON` / `UCLOUD_PRICE_TARGETS_FILE` | Choose an inline array or UTF-8 JSON target file; up to 20 complete configurations |
| `UCLOUD_PROJECT_ID` | Optional UCloud project; subaccounts may require it |
| `AUTODL_TOKEN`, `AUTODL_STORAGE_STATE_PATH` | Reserved for authenticated features; unused by the free homepage route |

`collect` exit codes: `0` when every provider succeeds, including no matches; `2` for partial provider failure; `1` for total failure or invalid configuration. Check the JSON as well as the exit code.

## Free Lambda collection

The default source is [Lambda's official instances page](https://lambda.ai/instances); no `.env` or credentials are needed:

```bash
gpu-price-monitor collect --providers lambda --pretty
```

The published rate is per GPU-hour. The whole-instance hourly total is derived by multiplying it by GPU count; resource units remain GiB / TiB. Region, country and zone are unknown and cannot be used as verified price filters. Listings are not inventory.

## AutoDL coverage

The source is [AutoDL's public homepage](https://www.autodl.com/home). It exposes ordinary and member tariff cards; member prices retain their conditions and must not be treated as generally available ordinary prices.

The homepage does not provide per-machine regional quotes or live inventory. GPU count is unknown. Region, country, zone and card-count filters therefore return structured errors. Lambda and AutoDL have different currencies, so the shared example does not apply a USD-only filter.

## Optional UCloud and Lambda API

UCloud uses a local `.env` and `configs/ucloud-targets.local.json`, both excluded from Git. Provide your own UCloud public/private keys and verify target configurations. Lambda uses `LAMBDA_API_KEY` only when you explicitly set `LAMBDA_SOURCE=api`. UCloud configuration example:

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=ucloud
UCLOUD_PRICE_TARGETS_FILE=configs/ucloud-targets.local.json
```

Replace target locations and specifications with configurations you have checked. Inspect local settings without network access:

```bash
gpu-price-monitor status --env-file .env
```

After filling keys and confirming the targets, explicitly run live verification:

```bash
gpu-price-monitor collect --env-file .env --providers ucloud --pretty
```

Python uses `settings=Settings.from_env(env_file=".env")`. Relative target paths resolve against the env file directory, or the working directory without an env file. Process variables override file values, including empty strings. Nonempty JSON and FILE sources in the same layer conflict. See [integration details](docs/DEPLOYMENT.md).

The [target file](configs/ucloud-targets.example.json) is a format example, not proof of availability. UCloud targets require Region, Zone, GPU type/count, CPU, memory in MB and disk definitions. Only full GPU instances with `MachineType=G`, `ChargeType=Dynamic` and `Count=1` are supported. See [integration details](docs/DEPLOYMENT.md). Do not apply a shared USD-only filter to Lambda and UCloud, since UCloud returns CNY.

Missing credentials and inline JSON target errors return provider-level `missing_credentials`, `missing_price_targets` / `invalid_price_targets`, preserving other providers' results. FILE read or validation failures raise a global `ConfigurationError` before any provider starts collection.

## Price semantics and license

Keep original amounts, currencies, units, resource configurations, sources, observation timestamps and effective dates. Lambda public `amount` is the listed GPU-hour rate; `instance_price` is the derived whole-instance total. The optional Lambda API and UCloud instead allocate an instance total across GPU count. Lambda API capacity regions remain separate from pricing scope. UCloud locations come from requested targets and are not independently verified by the response. Component prices, starting prices and sales inquiries remain distinct; listings and quotes do not guarantee availability.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before adding a provider. Only use read-only operations; do not create or buy resources to obtain a quote. [Apache-2.0](LICENSE) covers project code. Third-party data has separate usage and redistribution constraints; see [data policy](docs/DATA_POLICY.md).
