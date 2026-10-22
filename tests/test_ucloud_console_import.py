"""Synthetic Chrome export import; no browser, credentials or network access."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import stat
import tempfile
from unittest import TestCase
from unittest.mock import patch

from gpu_price_monitor.providers import ucloud_console_import as importer
from gpu_price_monitor.providers.ucloud_console_session import UCloudConsoleSession
from gpu_price_monitor.settings import Settings
from gpu_price_monitor.transport import FetchError

COOKIE = "session=synthetic-private-session; CSRF_TOKEN=synthetic%3Dcsrf; channel_key="


def command(action="GetDataForConsoleVersion", cookie=COOKIE, *, cookie_header=False):
    cookie_flag = "-H " + shlex.quote("Cookie: " + cookie) if cookie_header else "-b " + shlex.quote(cookie)
    return (" " + chr(92) + chr(10) + "  ").join([
        "curl " + shlex.quote("https://api.ucloud.cn?Action=" + action),
        "-H 'accept: application/json'",
        "-H 'x-unneeded-account-field: discard-this-private-header'",
        cookie_flag,
        "--data-raw " + shlex.quote("Action=" + action + "&ingress=1&UnusedSecret=discard-this-private-body"),
        "--compressed",
    ])


def write_source(path, text=None):
    path.write_text(command() if text is None else text, encoding="utf-8")
    path.chmod(0o600)


class UCloudConsoleImportTests(TestCase):
    def test_both_reviewed_actions_and_cookie_forms_become_only_minimal_session(self):
        for action in ("GetDataForConsoleVersion", "GetUHostInstancePrice"):
            for header in (False, True):
                with self.subTest(action=action, header=header):
                    state = importer._parse_curl(command(action, cookie_header=header))
                    self.assertEqual(set(state), {"format", "origin", "cookie"})
                    self.assertEqual(state["cookie"], COOKIE)
                    self.assertNotIn("discard-this-private", json.dumps(state))

    def test_import_output_private_and_loadable_without_mutating_existing_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o755)
            source, output = root / "request.txt", root / "session.json"
            write_source(source)
            importer.import_curl_session(source, output)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o755)
            session = UCloudConsoleSession.from_settings(Settings(ucloud_session_path=str(output)))
            self.assertNotIn(COOKIE, repr(session))
            another = root / "new-private-folder" / "session.json"
            importer.import_curl_session(source, another)
            self.assertEqual(stat.S_IMODE(another.parent.stat().st_mode), 0o700)

    def test_no_shell_command_or_network_executes_even_for_literal_shell_characters(self):
        cookie = "session=$(do_not_execute); CSRF_TOKEN=synthetic"
        with tempfile.TemporaryDirectory() as tmp, \
                patch("subprocess.run", side_effect=AssertionError("No subprocess")) as run, \
                patch("os.system", side_effect=AssertionError("No shell")) as system, \
                patch("gpu_price_monitor.transport._request_text", side_effect=AssertionError("No network")) as network:
            source, output = Path(tmp) / "request.txt", Path(tmp) / "session.json"
            write_source(source, command(cookie=cookie))
            importer.import_curl_session(source, output)
            self.assertEqual(json.loads(output.read_text())["cookie"], cookie)
            run.assert_not_called()
            system.assert_not_called()
            network.assert_not_called()

    def test_unreviewed_endpoint_method_action_or_curl_options_rejected(self):
        original = command()
        cases = [original.replace("api.ucloud.cn", "api.ucloud.cn.evil.example"),
                 original.replace("https://", "http://"),
                 original.replace("api.ucloud.cn?", "api.ucloud.cn:443?"),
                 original.replace("api.ucloud.cn?", "user@api.ucloud.cn?"),
                 original.replace("api.ucloud.cn?", "api.ucloud.cn/extra?"),
                 command("CreateUHostInstance"),
                 original.replace("&ingress=1", "&Action=GetDataForConsoleVersion&ingress=1"),
                 original.replace("&ingress=1", "&action=CreateUHostInstance&ingress=1"),
                 original.replace("--data-raw", "--data-binary"),
                 original + " -X GET", original + " --location", original + " --config secrets.txt",
                 original + " ; echo synthetic-private-session", original + " && touch ignored",
                 original + " -b 'CSRF_TOKEN=duplicate'",
                 original + " -H 'cookie: CSRF_TOKEN=duplicate'",
                 original.replace("&ingress=1", "&ingress=1").replace("'Action=GetDataForConsoleVersion&", "'Action=GetUHostInstancePrice&"),
                 "curl 'https://api.ucloud.cn?Action=GetDataForConsoleVersion' -b 'CSRF_TOKEN=synthetic' --data '@secret-file'",
                 command(cookie="session=synthetic-private-session"),
                 command(cookie="CSRF_TOKEN=%0D%0Ainjected")]
        for text in cases:
            with self.subTest(text=text[:60]), self.assertRaises(FetchError) as caught:
                importer._parse_curl(text)
            self.assertNotIn("synthetic-private-session", str(caught.exception))

    def test_refuses_overwrite_or_output_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "request.txt", Path(tmp) / "existing.json"
            write_source(source)
            output.write_text("preserve existing")
            with self.assertRaises(FetchError) as caught:
                importer.import_curl_session(source, output)
            self.assertEqual(caught.exception.code, "output_exists")
            self.assertEqual(output.read_text(), "preserve existing")
            link = Path(tmp) / "linked.json"
            link.symlink_to(output)
            with self.assertRaises(FetchError):
                importer.import_curl_session(source, link)
            self.assertEqual(output.read_text(), "preserve existing")

    def test_input_requires_bounded_private_regular_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "request.txt", Path(tmp) / "session.json"
            write_source(source)
            linked = Path(tmp) / "linked.txt"
            linked.symlink_to(source)
            with self.assertRaises(FetchError):
                importer.import_curl_session(linked, output)
            source.write_text("x" * (importer.MAX_SESSION_BYTES + 1))
            with self.assertRaises(FetchError):
                importer.import_curl_session(source, output)
            if os.name == "posix":
                write_source(source)
                source.chmod(0o644)
                with self.assertRaises(FetchError) as caught:
                    importer.import_curl_session(source, output)
                self.assertEqual(caught.exception.code, "private_file_required")
            self.assertFalse(output.exists())

    def test_cli_reports_result_without_printing_input_or_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, output = Path(tmp) / "request.txt", Path(tmp) / "session.json"
            write_source(source)
            with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
                code = importer.main(["--curl-file", str(source), "--output", str(output)])
            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertIn("saved privately", stdout.getvalue())
            self.assertNotIn(COOKIE, stdout.getvalue())
            with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
                code = importer.main(["--curl-file", str(source), "--output", str(output)])
            self.assertEqual(code, 1)
            self.assertIn("output_exists", stderr.getvalue())
            self.assertNotIn(COOKIE, stderr.getvalue())
            self.assertEqual(stdout.getvalue(), "")
