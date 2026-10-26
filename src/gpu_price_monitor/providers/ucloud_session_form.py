"""One-use localhost form for a caller-copied official read-only cURL request.

This does not access browser state. The user pastes their own request locally;
the existing data-only importer extracts the minimum credential. Nothing is
sent to a provider, executed as shell code, echoed, or logged by the server.
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import time
from urllib.parse import parse_qs

from ..transport import FetchError
from .ucloud_console_import import _parse_curl, _save_session
from .ucloud_console_session import MAX_SESSION_BYTES


def serve_import(output, *, timeout_seconds=600, ready=print):
    if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 600:
        raise FetchError("invalid_timeout", "Local import timeout must be 1–600 seconds.")
    nonce = secrets.token_urlsafe(32)
    completed = False
    origin = ""

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            # Chrome can open speculative idle connections. Bound each client
            # before reading headers so it cannot hold the one-use form open.
            self.connection.settimeout(5)

        def log_message(self, *_args):
            pass

        def reply(self, status, message):
            body = ("<!doctype html><meta charset=utf-8><title>UCloud 本地会话导入</title>"
                    "<style>body{font:18px system-ui;max-width:850px;margin:50px auto;padding:20px;line-height:1.7}"
                    "textarea{width:100%;height:230px;font:14px monospace}button{padding:12px 24px;font:inherit}</style>" + message).encode()
            self.send_response(status)
            for key, value in {"Content-Type": "text/html; charset=utf-8", "Content-Length": str(len(body)),
                               "Cache-Control": "no-store", "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff",
                               "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path != "/" or self.headers.get("Host") != origin.removeprefix("http://"):
                self.reply(404, "页面不存在。")
                return
            self.reply(200, "<h1>保存 UCloud 完整采集会话</h1><ol>"
                       "<li>回到已登录的 UCloud GPU 配置页，按 ⌘⌥I 打开开发者工具，选择 Network（网络）。</li>"
                       "<li>搜索 <b>GetDataForConsoleVersion</b> 并刷新页面；对该请求右键，选择 Copy → Copy as cURL。</li>"
                       "<li>把复制的文字粘贴到下框，点击保存。不要把这段文字粘到终端执行或发到聊天。</li></ol>"
                       "<p>也接受官方 GetUHostInstancePrice 询价请求。只在本机解析，丢弃其余请求内容，不上传、不执行命令。</p>"
                       f'<form method="post" action="/"><input type="hidden" name="nonce" value="{nonce}">'
                       '<textarea name="request" aria-label="官网 Copy as cURL 请求" autocomplete="off" spellcheck="false" required></textarea>'
                       '<p><button type="submit">保存最小会话到本机</button></p></form>')

        def do_POST(self):
            nonlocal completed
            if (completed or self.path != "/" or self.headers.get("Origin") != origin
                    or self.headers.get("Host") != origin.removeprefix("http://")
                    or self.headers.get("Content-Type") != "application/x-www-form-urlencoded"
                    or self.headers.get("Transfer-Encoding")):
                self.reply(403, "请求来源未通过本地校验。")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_SESSION_BYTES * 3 + 1024:
                    raise ValueError
                self.connection.settimeout(5)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError
                form = parse_qs(raw.decode("utf-8"), strict_parsing=True, max_num_fields=2)
                if (set(form) != {"nonce", "request"} or len(form["nonce"]) != 1 or len(form["request"]) != 1
                        or not secrets.compare_digest(form["nonce"][0], nonce)):
                    raise ValueError
                state = _parse_curl(form["request"][0])
                _save_session(state, output)
                self.reply(200, "<h1>已保存到本机</h1><p>最小会话文件权限为 0600；原请求没有保存。接下来由 Python 验证官方接口是否接受该会话。</p><p>可以关闭此页，并清空剪贴板。</p>")
                completed = True
            except (ValueError, OSError, UnicodeError, FetchError):
                self.reply(400, "<h1>未保存</h1><p>请复制官方 api.ucloud.cn 上的 GetDataForConsoleVersion 或 GetUHostInstancePrice 请求；已有输出文件不会覆盖。凭据或请求内容未记录。</p>")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    origin = f"http://127.0.0.1:{server.server_port}"
    ready(f"Local UCloud import: {origin}/")
    deadline = time.monotonic() + timeout_seconds
    try:
        while not completed and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not completed:
        raise FetchError("login_timeout", "Local session import timed out; no session was saved.")
