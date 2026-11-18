"""Serve the loopback GET-only synthetic Console and API."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from polysia.monitoring.console import ConsoleApplication  # noqa: E402
from polysia.monitoring.console_bundle import MEDIA_TYPES  # noqa: E402
from polysia.storage.console_commands import ConsoleCommandStore  # noqa: E402
from tests.fixtures.console_h1 import write_publication  # noqa: E402


def main(assets: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="polysia-ui-preview-") as directory:
        root = Path(directory)
        apps = {}
        templates = {}
        for scenario in ("fresh", "stale", "unknown"):
            folder = root / scenario
            folder.mkdir()
            now = datetime.now(UTC) - timedelta(minutes=10 if scenario == "stale" else 0)
            templates[scenario] = write_publication(folder, now=now)
            if scenario == "unknown":
                (folder / "publication.json").write_text('{"dataset_role":"SYNTHETIC"}')
            commands = ConsoleCommandStore(folder / "commands.sqlite3")
            commands.initialize()
            apps[scenario] = ConsoleApplication(
                folder / "publication.json", origin="https://fixture.example.com",
                verify=lambda _: ("synthetic-preview", "reader"), commands=commands,
                csrf_secret=b"synthetic-preview-only-not-a-real-secret",
            )

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = urlsplit(self.path)
                if route.path == "/":
                    self.send_body((ROOT / "frontend/index.html").read_bytes(), "text/html")
                    return
                asset = re.fullmatch(
                    r"/assets/([A-Za-z0-9_-]+\.(?:css|js|png|svg|woff2))", route.path
                )
                if asset:
                    path = assets / asset[1]
                    if path.is_file():
                        self.send_body(path.read_bytes(), MEDIA_TYPES[path.suffix])
                    else:
                        self.send_error(404)
                    return
                if not route.path.startswith("/api/console/v1/"):
                    self.send_error(404)
                    return
                scenario = parse_qs(urlsplit(self.headers.get("Referer", "")).query).get(
                    "preview", ["fresh"]
                )[0]
                if scenario == "error" and not route.path.endswith("/session"):
                    self.send_error(503, "Synthetic failure")
                    return
                app = apps.get(scenario, apps["fresh"])
                if scenario == "fresh":
                    value = templates["fresh"]
                    financial = value["financial_session"]
                    now = datetime.now(UTC) - timedelta(seconds=1)
                    value["published_at"] = financial["as_of"] = now.isoformat()
                    financial["account_observed_at"] = now.isoformat()
                    financial["expires_at"] = financial["account_valid_until"] = (
                        now + timedelta(seconds=30)
                    ).isoformat()
                    financial["remaining_authority"]["expires_at"] = (
                        now + timedelta(minutes=5)
                    ).isoformat()
                    (root / "fresh/publication.json").write_text(json.dumps(value))
                try:
                    value = app._gateway.get(route.path, route.query, "synthetic-preview", "reader")
                    if route.path.endswith("/session"):
                        value["bundle"] = "a" * 64
                    body = json.dumps(value).encode()
                except (KeyError, ValueError, LookupError):
                    self.send_error(400, "Synthetic query rejected")
                    return
                self.send_body(body, "application/json")

            def send_body(self, body: bytes, content_type: str) -> None:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                # Navigation may abort a local read before it finishes.
                with suppress(ConnectionError):
                    self.wfile.write(body)

            def do_POST(self) -> None:
                self.send_error(405, "Synthetic preview is read-only")

            def log_message(self, *_: object) -> None:
                pass

        server = HTTPServer(("127.0.0.1", 5173), Handler)
        print("Synthetic preview: http://127.0.0.1:5173/?preview=fresh", flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
