"""Offline UCloud quote contract checks; fixture amounts are not live prices."""

from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

from gpu_price_monitor.providers import ucloud
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

FIXTURES = Path(__file__).parent / "fixtures"
OBSERVED = "2026-10-15T09:15:00+00:00"
PUBLIC = "test-public-placeholder"
PRIVATE = "test-private-placeholder"


def target(**updates):
    item = {
        "Region": "cn-bj2", "Zone": "cn-bj2-02", "MachineType": "G", "GpuType": "T4",
        "GPU": 2, "CPU": 8, "Memory": 32768,
        "Disks": [{"IsBoot": True, "Size": 40, "Type": "CLOUD_SSD"}],
    }
    item.update(updates)
    return item


def settings_for(items=None, **updates):
    return Settings(
        providers=("ucloud",), max_retries=0,
        ucloud_public_key=PUBLIC, ucloud_private_key=PRIVATE,
        ucloud_price_targets_json=json.dumps([target()] if items is None else items),
        **updates,
    )


def response():
    return json.loads((FIXTURES / "ucloud-price.json").read_text(), parse_float=Decimal)


class UCloudTests(unittest.TestCase):
    def test_signature_matches_official_documentation_vector(self):
        # Public test credentials explicitly published by UCloud for this vector.
        params = {"Action": "DescribeUHostInstance", "Region": "cn-bj2", "Limit": 10,
                  "PublicKey": "ucloudsomeone@example.com1296235120854146120"}
        signature = ucloud.sign_parameters(params, "46f09bb9fab4f12dfc160dae12273d5332b5debe")
        self.assertEqual(signature, "cba5cf5ec4d4233d206b1b54951e3787350a642f")

    def test_signature_sorts_raw_parameters_and_uses_lowercase_bool(self):
        params = {"Z": True, "A": "a b&中文", "Count": 1, "B": False}
        expected = hashlib.sha1("Aa b&中文BfalseCount1Ztrueprivate".encode()).hexdigest()
        self.assertEqual(ucloud.sign_parameters(params, "private"), expected)

    @patch("gpu_price_monitor.providers.ucloud.request_json")
    def test_collect_posts_signed_form_without_sending_private_key(self, request):
        request.return_value = response()
        settings = settings_for(ucloud_project_id="org-private-project")
        quotes = ucloud.collect_quotes(settings=settings, observed_at=OBSERVED)
        args, kwargs = request.call_args
        self.assertEqual(args, ("https://api.ucloud.cn/", settings))
        self.assertEqual(kwargs["method"], "POST")
        self.assertTrue(kwargs["authenticated"])
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/x-www-form-urlencoded")
        body = kwargs["data"].decode()
        self.assertNotIn(PRIVATE, body)
        fields = {key: values[0] for key, values in parse_qs(body).items()}
        signature = fields.pop("Signature")
        self.assertEqual(signature, ucloud.sign_parameters(fields, PRIVATE))
        self.assertEqual(fields["Action"], "GetUHostInstancePrice")
        self.assertEqual(fields["PublicKey"], PUBLIC)
        self.assertEqual(fields["ProjectId"], "org-private-project")
        self.assertEqual(fields["ChargeType"], "Dynamic")
        self.assertEqual(fields["Count"], "1")
        self.assertNotIn("Quantity", fields)
        self.assertEqual(fields["Disks.0.IsBoot"], "True")
        self.assertEqual(fields["ShowPriceDetails"], "true")
        self.assertEqual(quotes[0]["amount"], "4.2")
        self.assertEqual(quotes[0]["instance_price"], {
            "amount": "8.4", "original_amount": "10.5", "currency": "CNY", "unit": "instance_hour",
            "details": {"UHost": "8", "UDisk": "0.4"},
            "original_details": {"UHost": "10", "UDisk": "0.5"},
        })
        encoded = json.dumps(quotes)
        for sensitive in (PUBLIC, PRIVATE, "org-private-project", "Signature"):
            self.assertNotIn(sensitive, encoded)
        self.assertEqual(quotes[0]["regions"], ["cn-bj2"])
        self.assertEqual(quotes[0]["zones"], ["cn-bj2-02"])
        self.assertEqual(quotes[0]["resources"]["memory_mb"], 32768)
        self.assertEqual(quotes[0]["account_scope"], "account_quote")
        self.assertEqual(quotes[0]["availability"], "unknown")
        self.assertEqual(quotes[0]["observed_at"], OBSERVED)

    def test_normalization_is_independent_of_callers_decimal_context(self):
        payload = response()
        payload["PriceSet"][0]["Price"] = 1
        with localcontext() as context:
            context.prec = 2
            quote = ucloud.parse_quote(payload, target(GPU=3), observed_at=OBSERVED)
        self.assertEqual(quote["amount"], "0.333333333333")
        self.assertEqual(quote["instance_price"]["amount"], "1")
        self.assertEqual(quote["normalization"]["rounding"], "ROUND_HALF_UP")

    def test_accepts_transport_decimal_prices_and_nested_details(self):
        payload = response()
        self.assertIsInstance(payload["PriceSet"][0]["Price"], Decimal)
        self.assertIsInstance(payload["PriceSet"][0]["PriceDetail"]["UDisk"], Decimal)
        quote = ucloud.parse_quote(payload, target(), observed_at=OBSERVED)
        self.assertEqual(quote["amount"], "4.2")
        self.assertEqual(quote["instance_price"]["details"]["UDisk"], "0.4")
        self.assertEqual(json.loads(json.dumps(quote)), quote)

    def test_original_price_is_optional_per_official_response_example(self):
        payload = {"RetCode": 0, "Action": "GetUHostInstancePriceResponse",
                   "PriceSet": [{"ChargeType": "Dynamic", "Price": 0.42}]}
        quote = ucloud.parse_quote(payload, target(GPU=1), observed_at=OBSERVED)
        self.assertEqual(quote["amount"], "0.42")
        self.assertNotIn("original_amount", quote["instance_price"])

    def test_http_200_api_error_is_not_a_price_and_does_not_echo_message(self):
        with self.assertRaises(FetchError) as captured:
            ucloud.parse_quote({"RetCode": 123, "Message": PRIVATE, "Action": "GetUHostInstancePriceResponse"}, target(), observed_at=OBSERVED)
        self.assertEqual(captured.exception.code, "provider_api_error")
        self.assertNotIn(PRIVATE, str(captured.exception))

    def test_rejects_bad_status_action_period_price_and_price_detail(self):
        bad = []
        for code in ("0", False, None):
            item = response()
            item["RetCode"] = code
            bad.append(item)
        item = response()
        item["Action"] = "CreateUHostInstanceResponse"
        bad.append(item)
        for rows in ([], [{"ChargeType": "Month", "Price": 1}], [response()["PriceSet"][0]] * 2):
            item = response()
            item["PriceSet"] = rows
            bad.append(item)
        for price in (True, -1, "NaN", "Infinity", None, 1e20, {}, "private-token"):
            item = response()
            item["PriceSet"][0]["Price"] = price
            bad.append(item)
        item = response()
        item["PriceSet"][0]["PriceDetail"] = {"UHost": "bad"}
        bad.append(item)
        for payload in bad:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                ucloud.parse_quote(payload, target(), observed_at=OBSERVED)

    @patch("gpu_price_monitor.providers.ucloud.request_json")
    def test_requires_credentials_and_targets_without_network(self, request):
        for settings, expected in (
            (replace(settings_for(), ucloud_private_key=None), "missing_credentials"),
            (replace(settings_for(), ucloud_public_key=None), "missing_credentials"),
            (replace(settings_for(), ucloud_private_key="  "), "missing_credentials"),
            (replace(settings_for(), ucloud_public_key="  "), "missing_credentials"),
            (replace(settings_for(), ucloud_price_targets_json=None), "missing_price_targets"),
        ):
            with self.subTest(expected=expected), self.assertRaises(FetchError) as captured:
                ucloud.collect_quotes(settings=settings, observed_at=OBSERVED)
            self.assertEqual(captured.exception.code, expected)
        request.assert_not_called()

    @patch("gpu_price_monitor.providers.ucloud.request_json")
    def test_rejects_unsafe_ambiguous_or_unsupported_targets_before_network(self, request):
        invalid = [[], {}, [target()] * 21]
        for update in (
            {"Action": "CreateUHostInstance"}, {"PublicKey": "injected"}, {"Signature": "injected"},
            {"Quantity": 1}, {"PrivateKey": "injected"}, {"Count": 2}, {"Count": True},
            {"ChargeType": "Month"}, {"MachineType": "O.BM"}, {"MachineType": "N"},
            {"GpuType": "T4/4"}, {"GpuType": "2080Ti-4C"}, {"GPU": 0}, {"GPU": True},
            {"CPU": -1}, {"Memory": 32}, {"Region": "cn-sh2"}, {"Zone": ""},
            {"Disks": []}, {"Disks": [{"IsBoot": False, "Size": 40, "Type": "CLOUD_SSD"}]},
            {"Disks": [{"IsBoot": True, "Size": 40, "Type": "CLOUD_SSD", "Unknown": "x"}]},
            {"Disks": [{"IsBoot": True, "Size": "40", "Type": "CLOUD_SSD"}]},
            {"Disks": [{"IsBoot": True, "Size": 40, "Type": "bad"}]},
            {"ShowPriceDetails": "true"},
        ):
            invalid.append([target(**update)])
        no_region = target()
        del no_region["Region"]
        invalid.extend([[no_region], [target(), target()], [target(), target(Quantity=1)]])
        for items in invalid:
            with self.subTest(items=items), self.assertRaises(FetchError) as captured:
                ucloud.collect_quotes(settings=settings_for(items), observed_at=OBSERVED)
            self.assertEqual(captured.exception.code, "invalid_price_targets")
        for raw in ("private-token", "[{\"Region\":1,\"Region\":2}]", "[NaN]", "x" * 131073):
            with self.subTest(raw=raw[:100]), self.assertRaises(FetchError):
                ucloud.load_targets(replace(settings_for(), ucloud_price_targets_json=raw))
        request.assert_not_called()

    def test_project_override_and_multiple_disks_are_explicit(self):
        item = target(ProjectId="org-target", Disks=[
            {"IsBoot": True, "Size": 40, "Type": "CLOUD_SSD"},
            {"IsBoot": False, "Size": 200, "Type": "CLOUD_RSSD", "BackupType": "NONE"},
        ])
        loaded = ucloud.load_targets(settings_for([item], ucloud_project_id="org-global"))[0]
        self.assertEqual(loaded["ProjectId"], "org-target")
        body = parse_qs(ucloud.build_request(loaded, PUBLIC, PRIVATE).decode())
        self.assertEqual(body["Disks.1.Size"], ["200"])
        self.assertEqual(body["Disks.1.IsBoot"], ["False"])
        self.assertNotIn("Disks", body)

    @patch("gpu_price_monitor.providers.ucloud.request_json")
    def test_a_failed_target_does_not_return_an_incomplete_success(self, request):
        request.side_effect = [response(), {"RetCode": 42, "Message": PRIVATE}]
        settings = settings_for([target(), target(Zone="cn-bj2-04")])
        with self.assertRaises(FetchError):
            ucloud.collect_quotes(settings=settings, observed_at=OBSERVED)
        self.assertEqual(request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
