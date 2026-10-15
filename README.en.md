# GPU Price Monitor

[Real JSON snapshot from 2026-10-15](examples/nebius-crusoe-2026-10-15.json): 18 USD on-demand records, including 15 numeric quotes and 3 sales inquiries. This is a historical API example, never a fallback for live requests.

An open-source library that collects GPU cloud rental prices from official sources and returns structured results through Python or a JSON CLI.

[中文](README.md) · [Plan](docs/PLAN.md) · [Data contract](docs/DATA_MODEL.md) · [Integration](docs/DEPLOYMENT.md) · [Roadmap](ROADMAP.md)

## Supported sources

**Nebius public Compute pricing documentation** and **Crusoe's public GPU instances pricing section** are implemented. Neither requires credentials. Lambda, UCloud and AutoDL are not implemented and return `not_implemented`. This version has not been published to PyPI; install from source.

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
| `gpu_models` | `--gpu` | Both providers |
| `currencies` | `--currency` | Both providers; no currency conversion |
| `billing_modes` | `--billing-mode` | Both providers |
| `regions` | `--region` | Nebius only; Crusoe returns `unsupported_filter` |
| `compute_countries`, `sales_countries` | `--country`, `--sales-country` | Cannot currently be verified; structured error |
| `zones`, `gpu_counts` | `--zone`, `--gpu-count` | Cannot currently be verified; structured error |

For example, request a Nebius region with `gpu-price-monitor collect --providers nebius --region eu-north1 --pretty`. Unknown locations and card counts remain unknown. A supported configuration field does not imply that every provider can apply it.

## Configuration

```bash
gpu-price-monitor status
gpu-price-monitor validate-config --config configs/collect.example.json
gpu-price-monitor collect --config configs/collect.example.json --pretty
```

The example enables Nebius and Crusoe and disables the unimplemented providers. It supports per-provider filters. Validation does not access providers or verify credentials. Use `--timeout` and `--max-retries` for request options.

Use [`.env.example`](.env.example) as a reference. **The program reads process environment variables; it does not automatically load `.env` files.** Your application, container or runner injects them.

| Variable | Purpose / default |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | Comma-separated default providers; `nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | Timeout; `30` seconds |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | Maximum retries; `2` |
| `LAMBDA_API_KEY` | Reserved for the future Lambda adapter |
| `NEBIUS_ACCESS_TOKEN` | Reserved for authenticated estimates; not needed for current collection |
| `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY` | Reserved for the future UCloud adapter |
| `AUTODL_TOKEN`, `AUTODL_STORAGE_STATE_PATH` | Reserved for the future AutoDL adapter |

`collect` exit codes: `0` when every provider succeeds, including no matches; `2` for partial provider failure; `1` for total failure or invalid configuration. Check the JSON as well as the exit code.

## Price semantics and license

Keep original amounts, currencies, units, resource configurations, sources, observation timestamps and effective dates. A Nebius GPU component is not an instance total. A starting price is not a firm current quote. Contact-sales entries have no amount. Public listed prices do not guarantee capacity or self-service purchasing.

Read [CONTRIBUTING.md](CONTRIBUTING.md) before adding a provider. Only use read-only operations; do not create or buy resources to obtain a quote. [Apache-2.0](LICENSE) covers project code. Third-party data has separate usage and redistribution constraints; see [data policy](docs/DATA_POLICY.md).
