"""Synthetic local session/protocol checks; no live credentials or network."""
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
from urllib.parse import parse_qs

from gpu_price_monitor.providers import ucloud_console_session as api
from gpu_price_monitor.settings import ConfigurationError, Settings
from gpu_price_monitor.transport import FetchError

COOKIE = "session=synthetic-private-session; CSRF_TOKEN=first%3Dcsrf; CSRF_TOKEN=last%3Dcsrf; U_CSRF_TOKEN=u%2Bcsrf; channel_key="


def write_session(path, cookie=COOKIE, **extra):
    path.write_text(json.dumps({"format": api.EXPORT_FORMAT, "origin": api.CONSOLE_ORIGIN,
                                "cookie": cookie, **extra}), encoding="utf-8")
    path.chmod(0o600)
    return Settings(ucloud_source="console", ucloud_session_path=str(path))


class UCloudConsoleSessionTests(TestCase):
    def test_settings_configure_console_without_reading_session_and_keep_path_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "prices.env"
            env_file.write_text("UCLOUD_SOURCE=console\nUCLOUD_SESSION_PATH=private/not-created.json\n")
            settings = Settings.from_env({}, env_file=env_file)
            self.assertEqual(settings.ucloud_source, "console")
            self.assertEqual(settings.ucloud_session_path, str(Path(tmp) / "private/not-created.json"))
            self.assertNotIn("not-created", repr(settings))
            override = Settings.from_env({"UCLOUD_SESSION_PATH": ""}, env_file=env_file)
            self.assertIsNone(override.ucloud_session_path)
        with self.assertRaises(ConfigurationError):
            Settings(ucloud_source="arbitrary")

    def test_explicit_minimal_file_is_loaded_once_and_never_exposed_by_repr(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.json"
            settings = write_session(path)
            session = api.UCloudConsoleSession.from_settings(settings)
            path.unlink()
            self.assertNotIn(COOKIE, repr(session))
            self.assertNotIn("synthetic-private-session", repr(session))
            with patch.object(api, "request_json", return_value={"RetCode": 0}) as transport:
                session.request("ListRegions", settings=settings)
                session.request("ListZones", {"Region": "cn-bj2"}, settings=settings)
                self.assertEqual(transport.call_count, 2)

    def test_loader_rejects_extra_fields_duplicate_keys_and_wrong_origin_without_secret_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.json"
            valid = {"format": api.EXPORT_FORMAT, "origin": api.CONSOLE_ORIGIN, "cookie": COOKIE}
            for content in (
                json.dumps({**valid, "extra": "synthetic-private-session"}),
                json.dumps({**valid, "origin": "https://other.example"}),
                json.dumps({**valid, "format": "unknown"}),
                json.dumps(valid)[:-1] + ', "cookie": "synthetic-private-session"}',
                "[\"synthetic-private-session\"]",
                json.dumps({**valid, "cookie": "CSRF_TOKEN=a\r\nInjected:secret"}),
                json.dumps({**valid, "cookie": 123}),
            ):
                with self.subTest(content=content[:30]):
                    path.write_text(content)
                    path.chmod(0o600)
                    with self.assertRaises(FetchError) as caught:
                        api.UCloudConsoleSession.from_settings(Settings(ucloud_session_path=str(path)))
                    self.assertEqual(caught.exception.code, "session_invalid")
                    self.assertNotIn("synthetic-private-session", str(caught.exception))
                    self.assertNotIn(str(path), str(caught.exception))

    def test_loader_rejects_symlink_oversize_and_nonprivate_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private.json"
            settings = write_session(path)
            link = Path(tmp) / "linked.json"
            link.symlink_to(path)
            with self.assertRaises(FetchError):
                api.UCloudConsoleSession.from_settings(Settings(ucloud_session_path=str(link)))
            path.write_bytes(b" " * (api.MAX_SESSION_BYTES + 1))
            with self.assertRaises(FetchError):
                api.UCloudConsoleSession.from_settings(settings)
            if os.name == "posix":
                write_session(path)
                path.chmod(0o644)
                with self.assertRaises(FetchError):
                    api.UCloudConsoleSession.from_settings(settings)
        with self.assertRaises(FetchError) as caught:
            api.UCloudConsoleSession.from_settings(Settings())
        self.assertEqual(caught.exception.code, "login_required")

    @patch.object(api, "request_json", return_value={"RetCode": 0, "PriceSet": []})
    def test_price_request_matches_services_cookie_precedence_and_has_fixed_origin(self, transport):
        session = api.UCloudConsoleSession(COOKIE)
        settings = Settings()
        payload = session.request("GetUHostInstancePrice", {
            "Region": "cn-bj2", "Zone": "cn-bj2-02", "ChargeType": "Dynamic",
            "GPU": 1, "Disks.0.Size": 20, "Fraction": Decimal("0.25"),
        }, settings=settings)
        self.assertEqual(payload["RetCode"], 0)
        args, kwargs = transport.call_args
        self.assertEqual(args, ("https://api.ucloud.cn?Action=GetUHostInstancePrice", settings))
        self.assertEqual(kwargs["headers"]["CSRF-Token"], "first=csrf")
        self.assertEqual(kwargs["headers"]["U-CSRF-Token"], "u+csrf")
        self.assertNotIn("channel-key", kwargs["headers"])
        self.assertEqual(kwargs["headers"]["Cookie"], COOKIE)
        self.assertEqual(kwargs["headers"]["Origin"], api.CONSOLE_ORIGIN)
        self.assertEqual(kwargs["headers"]["Referer"], api.PRICING_PAGE)
        self.assertEqual(kwargs["method"], "POST")
        self.assertTrue(kwargs["authenticated"])
        self.assertEqual(kwargs["max_response_bytes"], 16 * 1024 * 1024)
        self.assertEqual(parse_qs(kwargs["data"].decode())["Action"], ["GetUHostInstancePrice"])
        self.assertEqual(parse_qs(kwargs["data"].decode())["Disks.0.Size"], ["20"])

    @patch.object(api, "request_json", return_value={"RetCode": 0})
    def test_bootstrap_preserves_published_last_cookie_raw_encoding(self, transport):
        session = api.UCloudConsoleSession(COOKIE)
        session.request("GetDataForConsoleVersion", {"ingress": 1}, settings=Settings())
        self.assertEqual(transport.call_args.kwargs["headers"]["CSRF-Token"], "last%3Dcsrf")
        self.assertEqual(transport.call_args.kwargs["headers"]["U-CSRF-Token"], "u%2Bcsrf")

    @patch.object(api, "request_json")
    def test_actions_overrides_and_invalid_parameters_fail_before_network(self, transport):
        session = api.UCloudConsoleSession(COOKIE)
        for action, parameters in (
            ("CreateUHostInstance", {}), ("GetUHostInstancePrice&Action=Create", {}),
            ("ListRegions", {"Action": "CreateUHostInstance"}),
            ("ListRegions", {"action": "CreateUHostInstance"}),
            ("ListRegions", {"bad\nname": 1}), ("ListRegions", {"Region": {"secret": "hidden"}}),
            ("ListRegions", {"CPU": float("inf")}), ("ListRegions", {"CPU": Decimal("NaN")}),
        ):
            with self.subTest(action=action, parameters=parameters), self.assertRaises(FetchError):
                session.request(action, parameters, settings=Settings())
        transport.assert_not_called()

    @patch.object(api, "request_json")
    def test_invalid_csrf_is_rejected_before_network(self, transport):
        for cookie in ("session=synthetic-private-session", "CSRF_TOKEN=%0Asecret",
                       "CSRF_TOKEN=%ZZ", "CSRF_TOKEN=%E0%A4%A", "CSRF_TOKEN=" ):
            with self.subTest(cookie=cookie), self.assertRaises(FetchError) as caught:
                api.UCloudConsoleSession(cookie).request("ListRegions", settings=Settings())
            self.assertNotIn(cookie, str(caught.exception))
        transport.assert_not_called()

    @patch.object(api, "request_json")
    def test_http_success_alone_is_not_authenticated_success(self, transport):
        session = api.UCloudConsoleSession(COOKIE)
        for payload, code in (({"RetCode": 170, "Message": COOKIE}, "authentication_error"),
                              ({"RetCode": 172}, "authentication_error"),
                              ({"RetCode": 174}, "authentication_error"),
                              ({"RetCode": 123, "Message": COOKIE}, "provider_rejected"),
                              ({"RetCode": False}, "invalid_response"),
                              ({"RetCode": "0"}, "invalid_response"),
                              ({"Message": COOKIE}, "invalid_response")):
            transport.return_value = payload
            with self.subTest(code=code, retcode=payload.get("RetCode")), self.assertRaises(FetchError) as caught:
                session.request("ListRegions", settings=Settings())
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("synthetic-private-session", str(caught.exception))
