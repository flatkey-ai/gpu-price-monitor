"""Local session import uses same-origin/nonce checks and never executes cURL."""
import http.client
import json
import re
import socket
import tempfile
import threading
from pathlib import Path
from unittest import TestCase
from urllib.parse import urlencode, urlsplit
from unittest.mock import patch

from gpu_price_monitor.providers.ucloud_session_form import serve_import
from gpu_price_monitor.transport import FetchError

REQUEST = "curl 'https://api.ucloud.cn/?Action=GetDataForConsoleVersion' -b 'session=synthetic; CSRF_TOKEN=test' --data-raw 'Action=GetDataForConsoleVersion'"


class SessionFormTests(TestCase):
    def test_only_valid_same_origin_request_saves_minimal_private_file(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "session.json"
            ready, urls, errors = threading.Event(), [], []
            def announce(message):
                urls.append(message.split("Local UCloud import: ", 1)[1].rstrip("/"))
                ready.set()
            def run():
                try:
                    serve_import(output, timeout_seconds=5, ready=announce)
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=run, daemon=True)
            with patch("subprocess.run", side_effect=AssertionError("No shell")), patch("gpu_price_monitor.transport._request_text", side_effect=AssertionError("No provider network")):
                thread.start()
                self.assertTrue(ready.wait(2))
                origin = urls[0]
                port = urlsplit(origin).port
                def request(method, body=None, headers=None):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                    connection.request(method, "/", body=body, headers=headers or {})
                    response = connection.getresponse()
                    result = response.status, dict(response.getheaders()), response.read().decode()
                    connection.close()
                    return result
                # A browser preconnect must not block the real form request.
                idle = socket.create_connection(("127.0.0.1", port), timeout=2)
                self.addCleanup(idle.close)
                status, headers, html = request("GET")
                self.assertEqual(status, 200)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["Referrer-Policy"], "same-origin")
                self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
                nonce = re.search('name="nonce" value="([^"]+)"', html).group(1)
                form = urlencode({"nonce": nonce, "request": REQUEST})
                post_headers = {"Origin": origin, "Content-Type": "application/x-www-form-urlencoded"}
                for body, extra, expected in [
                    (form, {"Origin": "https://example.invalid"}, 403),
                    (urlencode({"nonce": "wrong", "request": REQUEST}), {}, 400),
                    (urlencode({"nonce": nonce, "request": REQUEST.replace("GetDataForConsoleVersion", "CreateUHostInstance")}), {}, 400),
                ]:
                    status, _, response = request("POST", body, {**post_headers, **extra})
                    self.assertEqual(status, expected)
                    self.assertNotIn("session=synthetic", response)
                    self.assertFalse(output.exists())
                status, _, response = request("POST", form, post_headers)
                self.assertEqual(status, 200)
                self.assertNotIn("session=synthetic", response)
                thread.join(2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(errors, [])
                state = json.loads(output.read_text())
                self.assertEqual(set(state), {"format", "origin", "cookie"})
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_invalid_timeout_is_rejected_before_starting_server(self):
        for timeout in [0, 601, True, 1.2]:
            with self.subTest(timeout=timeout), self.assertRaises(FetchError):
                serve_import("unused", timeout_seconds=timeout)
