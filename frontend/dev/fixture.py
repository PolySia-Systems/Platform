"""Loopback GET-only synthetic gateway for the Vite development entry."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from polysia.monitoring.console import ConsoleApplication  # noqa: E402
from polysia.storage.console_commands import ConsoleCommandStore  # noqa: E402
from tests.fixtures.console_h1 import write_publication  # noqa: E402


def main() -> None:
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
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except ConnectionError:
                    # Navigation/HMR may abort a local read before it finishes.
                    pass

            def do_POST(self) -> None:
                self.send_error(405, "Synthetic preview is read-only")

            def log_message(self, *_: object) -> None:
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        print(server.server_port, flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == "__main__":
    main()
