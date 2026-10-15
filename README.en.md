# GPU Price Monitor

An open-source project for tracking GPU cloud rental prices by location, hardware configuration and billing terms.

[中文](README.md) · [Implementation plan](docs/PLAN.md) · [Roadmap](ROADMAP.md)

## Status

Project scaffold only. The repository includes an implementation plan, provider research, a configuration example, a configuration-check CLI and CI. **Live collectors, storage, dashboards and notifications are not implemented. Daily collection is not enabled. There are no live prices in this repository.**

Initial providers: Nebius, Lambda, Crusoe, AutoDL and UCloud. The planned collection methods combine official APIs, public pricing pages and authorized browser sessions.

## Principles

- Keep compute location, purchasing country, currency, tax treatment and account pricing scope separate.
- Preserve original prices, units, source URLs, observation timestamps and effective dates.
- Distinguish instance totals, GPU-only components, starting prices, contract prices and sales inquiries.
- Track regional capacity separately from the geographical scope of a price.
- Compare matching configurations and billing terms; never treat collection failures as zero prices.
- Publish only an explicit allowlist of suitable public fields; keep credentials and private quotes private.

## Try the scaffold

Python 3.11+ is required. The current CLI uses only the standard library.

```bash
PYTHONPATH=src python3 -m gpu_price_monitor status
PYTHONPATH=src python3 -m gpu_price_monitor validate-config --config configs/monitor.example.json
```

All providers are disabled in the example. Configuration validation does not make an unimplemented collector operational.

## License

[Apache-2.0](LICENSE) for project code. Third-party content and account data have separate publication constraints; see [data policy](docs/DATA_POLICY.md).
