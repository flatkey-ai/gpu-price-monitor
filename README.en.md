# GPU Price Monitor

[Real JSON snapshot from 2026-10-15](examples/nebius-crusoe-2026-10-15.json): 18 USD on-demand records, including 15 numeric quotes and 3 sales inquiries. This is a historical API example, never a fallback for live requests.

An open-source library that collects GPU cloud rental prices from official sources and returns structured results through Python or a JSON CLI.

[中文](README.md) · [Plan](docs/PLAN.md) · [Data contract](docs/DATA_MODEL.md) · [Integration](docs/DEPLOYMENT.md) · [Roadmap](ROADMAP.md)

## Supported sources

Version 0.3.0 supports **Nebius, Crusoe, Lambda and UCloud**, with explicit env-file and local target-file loading. Nebius and Crusoe use public sources; Lambda and UCloud require your own credentials for read-only price requests. AutoDL is not implemented and returns `not_implemented`. Install from source; this version has not been published to PyPI.

Lambda and UCloud have offline fixture coverage. Credentials are absent in the current environment, so **authenticated live pricing has not been verified**. The public snapshot above does not include authenticated provider results.

The library owns fetching, parsing, filter verification and structured results. Callers own scheduling, storage, history, uploads, comparisons, alerts and dashboards. No Flatkey upload endpoint is built in.

## Install and collect

Python 3.11+ is required. No GPU is needed.

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
python3 -m pip install -e .
gpu-price-monitor collect --providers nebius,crusoe --currency USD --billing-mode on_demand --pretty
```

The `collect` command writes JSON to stdout and diagnostics to stderr. Your application can capture the result or redirect stdout to a file.

```python
import json
from gpu_price_monitor import collect_prices, Settings

result = collect_prices(
    providers=["nebius", "crusoe"],
    filters={"currencies": ["USD"], "billing_modes": ["on_demand"]},
    settings=Settings.from_env(),
)
print(json.dumps(result, ensure_ascii=False, indent=2))
```

The returned standard `dict` includes `schema_version`, `status`, UTC `collected_at`, `prices` and `provider_results`. Successful quotes remain available if another provider fails. Each provider reports its status, applied filters and errors. See [data semantics](docs/DATA_MODEL.md).

## Filters and location limits

| Python filter | Repeatable CLI option | Current support |
| --- | --- | --- |
| `gpu_models` | `--gpu` | All four implemented providers |
| `currencies` | `--currency` | All four; Lambda USD, UCloud CNY; no currency conversion |
| `billing_modes` | `--billing-mode` | All four; UCloud currently uses Dynamic on-demand only |
| `regions` | `--region` | Nebius and UCloud; Crusoe and Lambda return `unsupported_filter` |
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

The example enables Nebius and Crusoe; authenticated sources remain disabled until configured. It supports per-provider filters. Validation does not access providers or verify credentials. Use `--timeout` and `--max-retries` for request options.

Use [`.env.example`](.env.example) as a reference. By default, settings read only the process environment. To load a local file, explicitly pass CLI `--env-file .env` or Python `Settings.from_env(env_file=".env")`. The library does not search parent directories, modify `os.environ`, interpolate variables or execute shell expressions from the file.

| Variable | Purpose / default |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | Comma-separated default providers; `nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | Timeout; `30` seconds |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | Maximum retries; `2` |
| `LAMBDA_API_KEY` | Required for Lambda read-only catalog requests |
| `NEBIUS_ACCESS_TOKEN` | Reserved for authenticated estimates; not needed for current collection |
| `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY` | Required for UCloud account quotations |
| `UCLOUD_PRICE_TARGETS_JSON` / `UCLOUD_PRICE_TARGETS_FILE` | Choose an inline array or UTF-8 JSON target file; up to 20 complete configurations |
| `UCLOUD_PROJECT_ID` | Optional UCloud project; subaccounts may require it |
| `AUTODL_TOKEN`, `AUTODL_STORAGE_STATE_PATH` | Reserved for the future AutoDL adapter |

`collect` exit codes: `0` when every provider succeeds, including no matches; `2` for partial provider failure; `1` for total failure or invalid configuration. Check the JSON as well as the exit code.

## Authenticated collection

Use a local `.env` and `configs/ucloud-targets.local.json`, both excluded from Git. Fill your own `LAMBDA_API_KEY`, `UCLOUD_PUBLIC_KEY` and `UCLOUD_PRIVATE_KEY` in `.env`, then set:

```dotenv
GPU_PRICE_MONITOR_PROVIDERS=lambda,ucloud
UCLOUD_PRICE_TARGETS_FILE=configs/ucloud-targets.local.json
```

Replace target locations and specifications with configurations you have checked. Inspect local settings without network access:

```bash
gpu-price-monitor status --env-file .env
```

After filling keys and confirming the targets, explicitly run live verification:

```bash
gpu-price-monitor collect --env-file .env --providers lambda,ucloud --pretty
```

Python uses `settings=Settings.from_env(env_file=".env")`. Relative target paths resolve against the env file directory, or the working directory without an env file. Process variables override file values, including empty strings. Nonempty JSON and FILE sources in the same layer conflict. See [integration details](docs/DEPLOYMENT.md).

The [target file](configs/ucloud-targets.example.json) is a format example, not proof of availability. UCloud targets require Region, Zone, GPU type/count, CPU, memory in MB and disk definitions. Only full GPU instances with `MachineType=G`, `ChargeType=Dynamic` and `Count=1` are supported. See [integration details](docs/DEPLOYMENT.md). Do not apply a shared USD-only filter to Lambda and UCloud, since UCloud returns CNY.

Missing credentials and inline JSON target errors return provider-level `missing_credentials`, `missing_price_targets` / `invalid_price_targets`, preserving other providers' results. FILE read or validation failures raise a global `ConfigurationError` before any provider starts collection.

## Price semantics and license

Keep original amounts, currencies, units, resource configurations, sources, observation timestamps and effective dates. Lambda and UCloud divide the whole-instance hourly price by GPU count for `amount`, retaining the original in `instance_price`. Lambda capacity regions are separate from pricing scope. UCloud locations come from requested targets and are not echoed or independently verified by the quote response. A Nebius GPU component is not an instance total; starting prices and sales inquiries remain distinct. Neither catalog listings nor quotes guarantee availability.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before adding a provider. Only use read-only operations; do not create or buy resources to obtain a quote. [Apache-2.0](LICENSE) covers project code. Third-party data has separate usage and redistribution constraints; see [data policy](docs/DATA_POLICY.md).
