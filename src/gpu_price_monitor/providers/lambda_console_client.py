"""Read Lambda's session-authenticated JSON catalogs; never provision resources.

This is an explicitly selected internal console API, not Lambda's stable public
API. A caller supplies its own saved session. No browser, LLM, payment operation,
reservation, or public-page fallback runs during collection.
"""

from __future__ import annotations

from decimal import DecimalException

from . import lambda_console as parser
from .lambda_locations import describe_location, validated_applicability_locations
from ..lambda_frontend import verify_frontend_version
from ..lambda_session import LambdaConsoleSession
from ..settings import Settings
from ..transport import FetchError

SOURCE_URL = parser.SOURCE_URL
SOURCE_TYPE = parser.SOURCE_TYPE


def collect_result(*, settings: Settings, observed_at: str) -> dict:
    """Collect independent catalogs, retaining successful reads on partial failure."""
    session = LambdaConsoleSession(settings)
    prices, errors, sources, excluded, regions = [], [], [], [], []
    counts = {"instance_source_record_count": 0, "gpu_instance_quote_count": 0,
              "excluded_non_gpu_record_count": 0, "cluster_configuration_count": 0,
              "cluster_gpu_rate_tier_count": 0, "region_metadata_count": 0}
    for kind, url in (("instances", parser.INSTANCE_TYPES_URL),
                      ("clusters", parser.RESERVED_CLUSTER_TYPES_URL),
                      ("regions", parser.REGIONS_URL)):
        context = {"kind": kind, "source_url": url, "source_type": SOURCE_TYPE,
                   "status": "failed", "observed_at": observed_at}
        try:
            payload = session.get_json(url)
            if kind == "instances":
                catalog = parser.parse_instance_catalog(payload, observed_at=observed_at)
                prices.extend(catalog["prices"])
                excluded = catalog["excluded_non_gpu_records"]
                counts.update(instance_source_record_count=catalog["source_record_count"],
                              gpu_instance_quote_count=len(catalog["prices"]),
                              excluded_non_gpu_record_count=len(excluded))
                context["record_count"] = len(catalog["prices"])
            elif kind == "clusters":
                clusters = parser.parse_cluster_prices(payload, observed_at=observed_at)
                prices.extend(clusters)
                counts["cluster_configuration_count"] = len(clusters)
                counts["cluster_gpu_rate_tier_count"] = len({
                    (quote["gpu_model"], quote["gpu_variant"], quote["vram_gb"], quote["amount"])
                    for quote in clusters})
                context["record_count"] = len(clusters)
            else:
                regions = parser.parse_regions(payload)
                counts["region_metadata_count"] = len(regions)
                context["record_count"] = len(regions)
            context["status"] = "success"
        except FetchError as exc:
            errors.append({"source_url": url, "code": exc.code, "message": str(exc),
                           "retryable": exc.retryable})
        except (ValueError, TypeError, KeyError, DecimalException):
            errors.append({"source_url": url, "code": "parse_failed",
                           "message": "The Lambda console catalog schema or price units changed.",
                           "retryable": False})
        sources.append(context)
    verification = {"status": "not_requested", "reason_code": "no_price_catalog_succeeded"}
    if prices:
        verification = verify_frontend_version(session, settings)
        verified = verification.get("status") == "verified"
        for quote in prices:
            quote["price_applicability"]["verification_status"] = (
                "verified_current_frontend" if verified else "frontend_version_unverified")
            quote["price_applicability"]["evidence"]["runtime_version_check"] = verification
        if not verified:
            errors.append({"source_url": "https://cloud.lambda.ai/instances",
                           "code": "catalog_geography_unverified",
                           "message": "The current console price flow could not be matched to the reviewed version; shared catalog country/region applicability is withheld.",
                           "retryable": False})
    located = [quote for quote in prices if validated_applicability_locations(quote)]
    counts["shared_catalog_located_quote_count"] = len(located)
    counts["no_selectable_or_unverified_location_quote_count"] = len(prices) - len(located)
    selectable = {location["region"] for quote in located
                  for location in quote["price_applicability"]["locations"]}
    country_catalog = [{**describe_location(region),
                        "has_currently_selectable_gpu_catalog_quotes": region["name"] in selectable}
                       for region in regions]
    succeeded = sum(source["status"] == "success" for source in sources)
    return {
        "prices": prices, "errors": errors,
        "status": "success" if not errors else "partial" if succeeded else "failed",
        "authentication_method": "caller_supplied_session_cookie",
        "sources": sources, "regions_catalog": regions,
        "country_region_catalog": country_catalog,
        "price_applicability_verification": verification,
        "excluded_non_gpu_records": excluded, "excluded_non_gpu_record_count": len(excluded),
        "catalog_coverage": {"scope": "session_visible_instance_and_reserved_cluster_catalogs",
                             **counts, "all_prices_complete": False},
        "pricing_limitations": [
            "Internal console APIs can change; expired sessions fail explicitly and never fall back to public prices.",
            "The current standard console price flow shares a SKU catalog rate across its listed selectable regions; these are not independently obtained regional or globally uniform tariffs.",
            "Cluster GPU-hour rates follow the official frontend field; conflicting legacy totals are audit-only.",
            "Cluster duration, account eligibility and final checkout terms are unverified; catalog prices are not binding orders.",
            "Public-page-only configurations, individual contracts, negotiated rates and capacity-reservation prices are outside this source.",
        ],
        "gaps": [
            {"scope": "independent_regional_prices", "status": "not_established",
             "reason": "The standard console shares catalog prices across selectable SKU regions; separate regional quote requests are not made."},
            {"scope": "cluster_final_terms", "status": "unverified",
             "reason": "Duration-specific checkout, taxes, account eligibility and orderability were not queried."},
            {"scope": "negotiated_and_capacity_reservation_quotes", "status": "not_collected",
             "reason": "Catalog reads do not expose all private contracts or separately quoted reservations."},
        ],
    }
