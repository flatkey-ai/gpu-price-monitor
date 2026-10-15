# GPU Price Monitor

An open-source library for collecting GPU cloud rental prices from official APIs, public pricing pages and authorized browser sessions, and returning structured results to its caller.

[中文](README.md) · [Plan](docs/PLAN.md) · [Data contract](docs/DATA_MODEL.md) · [Integration](docs/DEPLOYMENT.md) · [Roadmap](ROADMAP.md)

## Status

This is a project scaffold with provider research, a configuration example, environment settings, a configuration-check CLI and CI. **Provider collectors and the `collect_prices` / `collect` interfaces are not implemented. No live prices are available, and this version has not been published to PyPI.** Passing configuration validation does not imply that collection is supported or that credentials work.

The initial provider plan covers Nebius, Crusoe, Lambda, UCloud and AutoDL. See [provider research](docs/PROVIDERS.md) for official sources and limitations.

## Library scope

The library will accept collection settings and filters, query providers, verify price units and filter application, and return quotes with sources, timestamps and per-provider errors.

Callers own scheduling, databases, price history, uploads, currency conversion, comparisons, alerts and dashboards. Flatkey and other users supply their own credentials through their environments. No Flatkey upload destination or business credentials are built into the library.

## Try the scaffold

Python 3.11+ is required. The current configuration-check CLI uses only the standard library.

```bash
git clone https://github.com/flatkey-ai/gpu-price-monitor.git
cd gpu-price-monitor
PYTHONPATH=src python3 -m gpu_price_monitor status
PYTHONPATH=src python3 -m gpu_price_monitor validate-config --config configs/collect.example.json
```

For an editable local installation:

```bash
python3 -m pip install -e .
gpu-price-monitor status
```

All providers in the collection example are disabled. A provider list in environment settings does not enable providers that the file disables.

## Environment settings

Use [`.env.example`](.env.example) as a reference. **The program reads the process environment; it does not automatically load `.env` files.** Your application, container or runner must inject those variables. Credentials should never be committed.

| Variable | Purpose / default |
| --- | --- |
| `GPU_PRICE_MONITOR_PROVIDERS` | Comma-separated providers; `nebius,crusoe` |
| `GPU_PRICE_MONITOR_TIMEOUT_SECONDS` | Request timeout; `30` seconds |
| `GPU_PRICE_MONITOR_MAX_RETRIES` | Maximum retries; `2` |
| `LAMBDA_API_KEY` | Lambda catalog API authentication |
| `NEBIUS_ACCESS_TOKEN` | Authenticated Nebius estimates; not required for public documents |
| `UCLOUD_PUBLIC_KEY`, `UCLOUD_PRIVATE_KEY` | UCloud read-only quotation credentials |
| `AUTODL_TOKEN` | Token for applicable AutoDL API operations |
| `AUTODL_STORAGE_STATE_PATH` | Path to an authorized browser session file |

Location, hardware and billing filters belong in collection configuration. API keys and browser state remain outside it.

## Planned result contract

The planned Python interface is `collect_prices(providers, filters)`. A planned `collect` CLI will write structured JSON to stdout and diagnostic logs to stderr. **Neither interface is available yet; these are design targets.**

Results will preserve original prices, currencies, units, resource configurations, geographical and account scope, observed and effective dates, source URLs, filter application and structured provider errors. Unknown regions remain unknown. Regional capacity is kept separate from the geographical scope of a quote. Successful providers may return results even when others fail.

Uploading or storing a result is an operation in the caller's application. See the [data contract](docs/DATA_MODEL.md) and [integration plan](docs/DEPLOYMENT.md).

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md) before adding a provider. Integration tests must use read-only operations; do not create or buy resources to obtain a quote.

[Apache-2.0](LICENSE) covers project code. Third-party content and account data have separate usage and redistribution constraints; see [data policy](docs/DATA_POLICY.md).
