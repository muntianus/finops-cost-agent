"""Zero-dependency HTTP microservice for FinOps Cost Agent."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from finops_service.analyzer import (
    SKU_CATALOG,
    FinOpsAnalyzer,
    FinOpsAuditStore,
    get_perfops_estate_preset,
)

SERVICE_VERSION = "1.1.0"


class FinOpsHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer holding shared FinOpsAnalyzer and SQLite store."""

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: type,
        analyzer: Optional[FinOpsAnalyzer] = None,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        db_path = os.environ.get("FINOPS_DB_PATH", "finops_audit.db")
        self.analyzer = analyzer or FinOpsAnalyzer(store=FinOpsAuditStore(db_path))


class FinOpsHTTPRequestHandler(BaseHTTPRequestHandler):
    """REST API handler for FinOps Cost Agent."""

    server: FinOpsHTTPServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("FINOPS_QUIET", "0") == "1":
            return
        super().log_message(format, *args)

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/health":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "finops-cost-agent",
                    "version": SERVICE_VERSION,
                },
            )
            return

        if path == "/api/v1/catalog/skus":
            provider = query.get("provider", [None])[0]
            if provider and provider in SKU_CATALOG:
                catalog_data = {provider: SKU_CATALOG[provider]}
            else:
                catalog_data = SKU_CATALOG
            self._send_json(
                200,
                {
                    "version": SERVICE_VERSION,
                    "providers": list(catalog_data.keys()),
                    "catalog": catalog_data,
                },
            )
            return

        if path == "/api/v1/presets/perfops-estate":
            preset = get_perfops_estate_preset()
            report = self.server.analyzer.analyze_estate(
                preset,
                persist=True,
                preset_name="perfops-estate",
            )
            report["estate"] = {
                "estate_name": preset["estate_name"],
                "vps_host": preset["vps_host"],
            }
            self._send_json(200, report)
            return

        if path == "/api/v1/audits":
            limit_raw = query.get("limit", ["25"])[0]
            try:
                limit = max(1, min(200, int(limit_raw)))
            except ValueError:
                limit = 25
            audits = self.server.analyzer.store.list_audits(limit=limit)
            self._send_json(
                200,
                {
                    "count": len(audits),
                    "audits": audits,
                },
            )
            return

        self._send_json(
            404,
            {
                "error": "not_found",
                "path": path,
                "endpoints": [
                    "GET /health",
                    "GET /api/v1/catalog/skus",
                    "POST /api/v1/analyze",
                    "GET /api/v1/presets/perfops-estate",
                    "GET /api/v1/audits",
                ],
            },
        )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path != "/api/v1/analyze":
            self._send_json(404, {"error": "not_found", "path": path})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Payload must be a JSON object")
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
            return

        persist = bool(payload.get("persist", True))
        preset_name = payload.get("preset_name")
        report = self.server.analyzer.analyze_estate(
            payload,
            persist=persist,
            preset_name=preset_name,
        )
        self._send_json(200, report)


def create_server(
    host: str = "0.0.0.0",
    port: int = 4030,
    db_path: Optional[str] = None,
) -> FinOpsHTTPServer:
    resolved_db = db_path or os.environ.get("FINOPS_DB_PATH", "finops_audit.db")
    analyzer = FinOpsAnalyzer(store=FinOpsAuditStore(resolved_db))
    return FinOpsHTTPServer((host, port), FinOpsHTTPRequestHandler, analyzer=analyzer)


def run_server(host: str = "0.0.0.0", port: int = 4030, db_path: Optional[str] = None) -> None:
    server = create_server(host=host, port=port, db_path=db_path)
    print(f"FinOps Cost Agent v{SERVICE_VERSION} listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
