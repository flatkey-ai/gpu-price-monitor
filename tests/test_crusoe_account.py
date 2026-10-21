"""Crusoe account reads use official request signing and remain audit-only."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gpu_price_monitor.providers import crusoe_account
from gpu_price_monitor.settings import ConfigurationError
from gpu_price_monitor.transport import FetchError

ORGANIZATION = "11111111-2222-4333-8444-555555555555"
CONTRACT = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
PATH = f"/v1/organizations/{ORGANIZATION}/reservations"
OBSERVED = "2026-10-21T12:00:00+00:00"
# Synthetic, never an account credential; raw key bytes: crusoe-test-secret.
SECRET = "Y3J1c29lLXRlc3Qtc2VjcmV0"


def settings(**overrides):
    values = {"crusoe_access_key_id": "testAccessKey", "crusoe_secret_key": SECRET,
              "crusoe_organization_id": ORGANIZATION, "timeout_seconds": 10, "max_retries": 0}
    values.update(overrides)
    return SimpleNamespace(**values)


def item(**overrides):
    # Minimal synthetic Reservation matching the official OpenAPI shape.
    values = {"id": CONTRACT, "reservation_type": "RIPA", "product_line": "h100",
              "duration": 12, "quantity": 64, "used_quantity": 32,
              "locations": ["us-east1"], "price": "6.25",
              "projects": ["private-project-id"], "vm_ids": ["private-vm-id"],
              "contract_start_date": "2026-01-01T00:00:00Z",
              "contract_end_date": "2027-01-01T00:00:00Z",
              "delivery_deadline": "2026-01-01T00:00:00Z",
              "date_delivered": "2025-12-31T23:00:00Z"}
    values.update(overrides)
    return values


def parse(items=None):
    return crusoe_account.parse_contracts({"items": [item()] if items is None else items}, observed_at=OBSERVED)


class CrusoeAccountTests(unittest.TestCase):
    def test_official_payload_signature_matches_independent_openssl_vector(self):
        # Independently verified with openssl dgst -sha256 -mac HMAC using the
        # fixed request payload, including blank query and final newline.
        headers = crusoe_account.signed_get_headers(
            PATH, access_key_id="testAccessKey", secret_key=SECRET, timestamp=OBSERVED)
        self.assertEqual(headers, {
            "X-Crusoe-Timestamp": OBSERVED,
            "Authorization": "Bearer 1.0:testAccessKey:c3gz8gJH7GdYXR1pXovfeNTUE31G_gefvb8GgRwONnw",
        })
        padded = crusoe_account.signed_get_headers(
            PATH, access_key_id="testAccessKey", secret_key="eA==", timestamp=OBSERVED)
        unpadded = crusoe_account.signed_get_headers(
            PATH, access_key_id="testAccessKey", secret_key="eA", timestamp=OBSERVED)
        self.assertEqual(padded, unpadded)

    def test_signer_cannot_sign_mutations_queries_external_urls_or_arbitrary_paths(self):
        for path in ("https://untrusted.invalid" + PATH, PATH + "?status=effective",
                     PATH + "/new", PATH.replace("reservations", "compute/vms/instances"),
                     PATH + "\r\nX-Key:leak", "/v1/organizations/../../reservations"):
            with self.subTest(path=path), self.assertRaises(ConfigurationError):
                crusoe_account.signed_get_headers(path, access_key_id="testAccessKey",
                                                  secret_key=SECRET, timestamp=OBSERVED)

    def test_contracts_preserve_raw_amount_without_inventing_gpu_hour_or_currency(self):
        q = parse()[0]
        self.assertEqual(q["price_as_returned"], "6.25")
        self.assertEqual(q["product_line"], "h100")
        self.assertEqual(q["contract_location_constraints"], ["us-east1"])
        self.assertEqual(q["quantity_as_returned"], 64)
        self.assertEqual(q["duration_as_returned"], "12")
        self.assertEqual(q["account_scope"], "account_contract_audit")
        for name in ("currency", "unit", "gpu_model", "duration_unit"):
            self.assertIsNone(q[name])
        for name in ("currency_verified", "hourly_unit_verified", "gpu_product_verified",
                     "price_admissible_as_gpu_hour_quote"):
            self.assertIs(q[name], False)
        self.assertNotIn("amount", q)
        self.assertNotIn("gpu_count", q)
        self.assertNotIn("compute_countries", q)
        self.assertNotIn("regions", q)

    def test_cpu_contract_is_not_mislabeled_gpu_and_delivery_dates_can_be_unknown(self):
        q = parse([item(product_line="c1a", locations=[], date_delivered="", delivery_deadline="")])[0]
        self.assertEqual(q["product_line"], "c1a")
        self.assertIsNone(q["gpu_model"])
        self.assertIsNone(q["date_delivered"])
        self.assertIsNone(q["delivery_deadline"])
        self.assertEqual(q["contract_location_constraints"], [])

    def test_only_audited_whitelist_survives_and_private_identifiers_are_hashed(self):
        q = parse([item(organization_id=ORGANIZATION, secret_key=SECRET,
                        cookie="private-cookie", ssh_key="private-ssh")])[0]
        encoded = json.dumps(q)
        for private_value in (CONTRACT, ORGANIZATION, SECRET, "private-project-id", "private-vm-id",
                              "private-cookie", "private-ssh"):
            self.assertNotIn(private_value, encoded)
        self.assertEqual(len(q["contract_reference_sha256"]), 64)
        self.assertEqual(q["observed_at"], OBSERVED)
        self.assertEqual(json.loads(encoded), q)

    def test_changed_top_level_and_unhandled_pagination_fail_instead_of_partial_output(self):
        for value in ({}, {"items": None}, {"items": [item()], "nextPageToken": "more"},
                      {"items": [item()], "total": 2}, {"code": "bad_credential"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                crusoe_account.parse_contracts(value, observed_at=OBSERVED)
        self.assertEqual(parse([]), [])
        with patch.object(crusoe_account, "MAX_CONTRACTS", 0), self.assertRaises(ValueError):
            parse()

    def test_amounts_timestamps_counts_locations_and_duplicates_are_checked(self):
        mutations = [{"price": v} for v in (None, 6.25, "-1", "NaN", "1e3", "$6.25")]
        mutations += [{"quantity": v} for v in (True, -1, "64")]
        mutations += [{"locations": v} for v in ("us-east1", ["us-east1", "us-east1"], ["https://other.invalid"])]
        mutations += [{"contract_start_date": "not-a-date"}, {"duration": float("inf")}, {"id": "private"}]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                parse([item(**mutation)])
        duplicate = deepcopy(item())
        duplicate["id"] = duplicate["id"].upper()
        with self.assertRaises(ValueError):
            parse([item(), duplicate])

    @patch("gpu_price_monitor.providers.crusoe_account.request_json")
    def test_missing_or_invalid_credentials_fail_before_any_request(self, request):
        variants = [settings(**{key: None}) for key in
                    ("crusoe_access_key_id", "crusoe_secret_key", "crusoe_organization_id")]
        variants += [settings(crusoe_secret_key=v) for v in ("A", "not+urlsafe/", "bad\nheader", "")]
        variants += [settings(crusoe_organization_id="../../private"),
                     settings(crusoe_access_key_id="bad\r\nAuthorization:injected")]
        for config in variants:
            with self.subTest(config=config), self.assertRaises(ConfigurationError):
                crusoe_account.collect_result(settings=config, observed_at=OBSERVED)
        request.assert_not_called()

    @patch("gpu_price_monitor.providers.crusoe_account._request_time", return_value=OBSERVED)
    @patch("gpu_price_monitor.providers.crusoe_account.request_json")
    def test_collection_is_one_fixed_signed_get_with_redirect_rejection_and_audit_only(self, request, clock):
        request.return_value = {"items": [item()]}
        config = settings()
        result = crusoe_account.collect_result(settings=config, observed_at=OBSERVED)
        request.assert_called_once_with(
            "https://api.cloud.crusoe.ai" + PATH, config, method="GET",
            headers={"X-Crusoe-Timestamp": OBSERVED,
                     "Authorization": "Bearer 1.0:testAccessKey:c3gz8gJH7GdYXR1pXovfeNTUE31G_gefvb8GgRwONnw"},
            authenticated=True,
        )
        self.assertEqual(result["prices"], [])
        self.assertIs(result["audit_only"], True)
        self.assertEqual(result["contract_record_count"], 1)
        self.assertEqual(result["authentication_method"], "crusoe_hmac_sha256_v1_0")
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertNotIn(ORGANIZATION, json.dumps(result))

    @patch("gpu_price_monitor.providers.crusoe_account.request_json")
    def test_auth_failure_does_not_try_public_page_or_organization_discovery(self, request):
        request.side_effect = FetchError("authentication_error", "Provider rejected credentials.")
        with self.assertRaises(FetchError) as caught:
            crusoe_account.collect_result(settings=settings(), observed_at=OBSERVED)
        self.assertEqual(caught.exception.code, "authentication_error")
        self.assertEqual(request.call_count, 1)

    @patch("gpu_price_monitor.providers.crusoe_account.request_json")
    def test_bad_responses_fail_with_generic_error_without_echoing_account_body(self, request):
        request.return_value = {"private_response": "private-sensitive-body"}
        with self.assertRaises(FetchError) as caught:
            crusoe_account.collect_result(settings=settings(), observed_at=OBSERVED)
        self.assertEqual(caught.exception.code, "parse_failed")
        self.assertNotIn("private-sensitive-body", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
