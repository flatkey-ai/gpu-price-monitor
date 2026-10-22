"""Import an explicitly supplied Chrome Copy as cURL request as data only.

The caller saves a request from their logged-in UCloud console. This utility
never executes shell commands, contacts a provider, accesses a browser profile,
or uses an LLM. Only the minimal Cookie session is written to a private file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import sys
from urllib.parse import parse_qs, urlsplit

from ..transport import FetchError
from .ucloud_console_session import (CONSOLE_ORIGIN, EXPORT_FORMAT, MAX_SESSION_BYTES,
                                     _cookie_pairs, _csrf_headers)

_IMPORT_ACTIONS = frozenset({"GetDataForConsoleVersion", "GetUHostInstancePrice"})


def _invalid() -> FetchError:
    return FetchError("invalid_curl_export", "Supply a saved Chrome Copy as cURL request for an approved UCloud console catalog or price action.")


def _read_curl(path: str | Path) -> str:
    descriptor = None
    try:
        source = Path(path).expanduser()
        if source.is_symlink():
            raise _invalid()
        descriptor = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_SESSION_BYTES:
            raise _invalid()
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise FetchError("private_file_required", "The supplied cURL file must be owned by you and readable only by you; set its permissions to 600.")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            raw = stream.read(MAX_SESSION_BYTES + 1)
        if len(raw) > MAX_SESSION_BYTES:
            raise _invalid()
        return raw.decode("utf-8-sig")
    except FetchError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError):
        raise _invalid() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parse_curl(text: str) -> dict:
    """Parse a bounded command string without invoking a command interpreter."""
    try:
        if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_SESSION_BYTES:
            raise _invalid()
        # Chrome's multi-line shell export uses backslash-newline continuations;
        # shlex does not remove these on its own.
        continued = text.replace(chr(92) + "\r\n", "").replace(chr(92) + "\n", "")
        argv = shlex.split(continued, posix=True)
        if len(argv) < 2 or argv[0] != "curl":
            raise _invalid()
        url = body = cookie = method = None
        index = 1
        while index < len(argv):
            flag = argv[index]
            if flag == "--compressed":
                index += 1
                continue
            if flag in {"--url", "-H", "--header", "-b", "--cookie", "--data-raw", "--data", "-X", "--request"}:
                if index + 1 >= len(argv):
                    raise _invalid()
                value = argv[index + 1]
                index += 2
                if flag == "--url":
                    if url is not None:
                        raise _invalid()
                    url = value
                elif flag in {"-b", "--cookie"}:
                    if cookie is not None:
                        raise _invalid()
                    cookie = value
                elif flag in {"-H", "--header"}:
                    name, separator, header_value = value.partition(":")
                    if not separator or not name or "\r" in value or "\n" in value:
                        raise _invalid()
                    if name.lower() == "cookie":
                        if cookie is not None:
                            raise _invalid()
                        cookie = header_value.strip()
                elif flag in {"--data-raw", "--data"}:
                    if body is not None or value.startswith("@"):
                        raise _invalid()
                    body = value
                else:
                    if method is not None or value != "POST":
                        raise _invalid()
                    method = value
            elif flag.startswith("https://") and url is None:
                url = flag
                index += 1
            else:
                # Extra URLs, shell operators and unreviewed cURL options are
                # rejected as data; no subprocess or shell is ever invoked.
                raise _invalid()
        if url is None or body is None or cookie is None:
            raise _invalid()
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "api.ucloud.cn"
                or parsed.path not in {"", "/"} or parsed.fragment):
            raise _invalid()
        query = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=256)
        values = parse_qs(body, keep_blank_values=True, strict_parsing=True, max_num_fields=256)
        action = query.get("Action")
        if (set(query) != {"Action"} or not isinstance(action, list) or len(action) != 1
                or action[0] not in _IMPORT_ACTIONS or values.get("Action") != action
                or any(name.lower() == "action" and name != "Action" for name in values)):
            raise _invalid()
        _cookie_pairs(cookie)
        _csrf_headers(cookie)
        return {"format": EXPORT_FORMAT, "origin": CONSOLE_ORIGIN, "cookie": cookie}
    except FetchError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise _invalid() from None


def _save_session(state: dict, output: str | Path) -> None:
    parent_descriptor = descriptor = None
    created = False
    try:
        destination = Path(output).expanduser()
        if destination.name in {"", ".", ".."}:
            raise ValueError
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.parent.is_symlink():
            raise ValueError
        parent_descriptor = os.open(destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                    | getattr(os, "O_NOFOLLOW", 0))
        parent_info = os.fstat(parent_descriptor)
        if not stat.S_ISDIR(parent_info.st_mode):
            raise ValueError
        if os.name == "posix" and (parent_info.st_uid != os.getuid() or parent_info.st_mode & 0o022):
            raise ValueError
        descriptor = os.open(destination.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600, dir_fd=parent_descriptor)
        created = True
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            descriptor = None
            json.dump(state, stream, ensure_ascii=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise FetchError("output_exists", "The output already exists; choose a new private session file.") from None
    except (OSError, ValueError, TypeError, UnicodeError, NotImplementedError):
        if created and parent_descriptor is not None:
            try:
                os.unlink(destination.name, dir_fd=parent_descriptor)
            except OSError:
                pass
        raise FetchError("output_invalid", "Cannot write the new session file in the selected private directory.") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if parent_descriptor is not None:
            os.close(parent_descriptor)


def import_curl_session(curl_file: str | Path, output: str | Path) -> None:
    """Read one explicitly supplied export and write a new minimal session."""
    _save_session(_parse_curl(_read_curl(curl_file)), output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a saved UCloud Chrome Copy as cURL request as data; no command execution or network.")
    parser.add_argument("--curl-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        import_curl_session(args.curl_file, args.output)
    except FetchError as exc:
        print(f"UCloud session import: {exc.code}: {exc}", file=sys.stderr)
        return 1
    print("UCloud session saved privately. Set UCLOUD_SOURCE=console and UCLOUD_SESSION_PATH to the new file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
