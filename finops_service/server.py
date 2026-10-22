"""Zero-dependency HTTP microservice for FinOps Cost Agent."""

from __future__ import annotations

import copy
import hmac
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, NamedTuple, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from finops_service.analyzer import (
    SKU_CATALOG,
    FinOpsAnalyzer,
    FinOpsAuditStore,
    get_perfops_estate_preset,
)

SERVICE_VERSION = "1.1.0"

DEFAULT_MAX_BODY_BYTES = 1024 * 1024  # 1 MiB for regular requests
DEFAULT_MAX_BULK_BODY_BYTES = 8 * 1024 * 1024  # 8 MiB for bulk analysis payloads
BULK_ENDPOINTS = frozenset({"/api/v1/analyze"})
PERFOPS_PRESET_NAME = "perfops-estate"


class Route(NamedTuple):
    method: str
    path: str
    handler: str  # FinOpsHTTPRequestHandler method name
    public: bool = False  # True = served without the bearer token


# Every route the service answers. tests/test_openapi_contract.py keeps this
# table and docs/api/openapi.json in lockstep; the GET 404 body lists it too.
ROUTES: Tuple[Route, ...] = (
    Route("GET", "/health", "_get_health", public=True),
    Route("GET", "/api/v1/catalog/skus", "_get_catalog"),
    Route("POST", "/api/v1/analyze", "_post_analyze"),
    Route("GET", "/api/v1/presets/perfops-estate", "_get_preset"),
    Route("GET", "/api/v1/audits", "_get_audits"),
)
_ROUTE_INDEX = {(r.method, r.path): r for r in ROUTES}

logger = logging.getLogger(__name__)


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r, using %d", name, raw, default)
        return default
    if value <= 0:
        logger.warning("Ignoring non-positive %s=%r, using %d", name, raw, default)
        return default
    return value


def _resolve_api_token(api_token: Optional[str]) -> Optional[str]:
    """Explicit argument wins; otherwise read FINOPS_API_TOKEN (empty disables auth)."""
    raw = api_token if api_token is not None else os.environ.get("FINOPS_API_TOKEN")
    token = (raw or "").strip()
    return token or None


def build_preset_report(
    analyzer: FinOpsAnalyzer,
    preset_name: str = PERFOPS_PRESET_NAME,
    persist: bool = False,
    audit_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the estate preset report, optionally persisting it once."""
    preset = get_perfops_estate_preset()
    report = analyzer.analyze_estate(preset, persist=persist, preset_name=preset_name)
    if audit_id is not None:
        report["audit_id"] = audit_id
    if timestamp is not None:
        report["timestamp"] = timestamp
    report["estate"] = {
        "estate_name": preset["estate_name"],
        "vps_host": preset["vps_host"],
    }
    return report


def seed_preset_audits(analyzer: FinOpsAnalyzer) -> Dict[str, Dict[str, Any]]:
    """Seed built-in presets once at startup and return an in-memory report cache.

    Persistence happens only when no audit for the preset exists yet, so repeated
    restarts (and every GET) leave the SQLite database untouched.
    """
    existing = analyzer.store.get_latest_audit_id(PERFOPS_PRESET_NAME)
    if existing is None:
        report = build_preset_report(analyzer, persist=True)
        logger.info("Seeded preset audit %s into %s", report["audit_id"], analyzer.store.db_path)
    else:
        report = build_preset_report(
            analyzer,
            persist=False,
            audit_id=existing["audit_id"],
            timestamp=existing["created_at"],
        )
    return {PERFOPS_PRESET_NAME: report}


class FinOpsHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer holding shared FinOpsAnalyzer, SQLite store, and preset cache."""

    def __init__(
        self,
        server_address: Tuple[str, int],
        RequestHandlerClass: type,
        analyzer: Optional[FinOpsAnalyzer] = None,
        api_token: Optional[str] = None,
        max_body_bytes: Optional[int] = None,
        max_bulk_body_bytes: Optional[int] = None,
    ) -> None:
        super().__init__(server_address, RequestHandlerClass)
        db_path = os.environ.get("FINOPS_DB_PATH", "finops_audit.db")
        self.analyzer = analyzer or FinOpsAnalyzer(store=FinOpsAuditStore(db_path))
        self.api_token = _resolve_api_token(api_token)
        self.max_body_bytes = (
            max_body_bytes
            if max_body_bytes is not None
            else _env_positive_int("FINOPS_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)
        )
        self.max_bulk_body_bytes = (
            max_bulk_body_bytes
            if max_bulk_body_bytes is not None
            else _env_positive_int("FINOPS_MAX_BULK_BODY_BYTES", DEFAULT_MAX_BULK_BODY_BYTES)
        )
        # Presets are read from memory; SQLite is only written by the one-time seed above.
        self.preset_cache = seed_preset_audits(self.analyzer)
        if self.api_token is None:
            logger.warning(
                "FINOPS_API_TOKEN is not set: API authentication is disabled and all endpoints are public"
            )


class FinOpsHTTPRequestHandler(BaseHTTPRequestHandler):
    """REST API handler for FinOps Cost Agent."""

    server: FinOpsHTTPServer  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("FINOPS_QUIET", "0") == "1":
            return
        super().log_message(format, *args)

    def _send_json(
        self,
        status_code: int,
        payload: Dict[str, Any],
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _is_authorized(self) -> bool:
        expected = self.server.api_token
        if expected is None:
            return True
        header = self.headers.get("Authorization", "")
        scheme, _, supplied = header.partition(" ")
        if scheme.lower() != "bearer":
            return False
        supplied = supplied.strip()
        if not supplied:
            return False
        return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

    def _reject_unauthorized(self) -> None:
        self._send_json(
            401,
            {
                "error": "unauthorized",
                "detail": "Missing or invalid bearer token. Set the Authorization header.",
            },
            extra_headers={"WWW-Authenticate": 'Bearer realm="finops-cost-agent"'},
        )

    def _body_limit_for(self, path: str) -> int:
        if path in BULK_ENDPOINTS:
            return self.server.max_bulk_body_bytes
        return self.server.max_body_bytes

    def _read_request_body(self, limit: int) -> Optional[bytes]:
        """Read the body, enforcing size limits. Returns None when a response was sent."""
        transfer_encoding = (self.headers.get("Transfer-Encoding") or "").strip().lower()
        if transfer_encoding and transfer_encoding != "identity":
            self.close_connection = True
            self._send_json(
                411,
                {
                    "error": "length_required",
                    "detail": "Chunked transfer encoding is not supported; send Content-Length.",
                },
                extra_headers={"Connection": "close"},
            )
            return None

        raw_length = self.headers.get("Content-Length")
        if raw_length is None or raw_length.strip() == "":
            return b"{}"
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError):
            self.close_connection = True
            self._send_json(
                400,
                {"error": "invalid_content_length", "detail": "Content-Length must be an integer."},
                extra_headers={"Connection": "close"},
            )
            return None

        if content_length < 0:
            self.close_connection = True
            self._send_json(
                400,
                {"error": "invalid_content_length", "detail": "Content-Length must be non-negative."},
                extra_headers={"Connection": "close"},
            )
            return None

        if content_length > limit:
            self.close_connection = True
            self._send_json(
                413,
                {
                    "error": "payload_too_large",
                    "detail": f"Request body exceeds the {limit} byte limit.",
                    "limit_bytes": limit,
                    "received_bytes": content_length,
                },
                extra_headers={"Connection": "close"},
            )
            return None

        if content_length == 0:
            return b"{}"
        return self.rfile.read(content_length)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        route = _ROUTE_INDEX.get((method, path))

        # Only public routes skip auth; unknown paths answer 401 before 404.
        if (route is None or not route.public) and not self._is_authorized():
            self._reject_unauthorized()
            return

        if route is None:
            body: Dict[str, Any] = {"error": "not_found", "path": path}
            if method == "GET":
                body["endpoints"] = [f"{r.method} {r.path}" for r in ROUTES]
            self._send_json(404, body)
            return

        getattr(self, route.handler)(path, parse_qs(parsed.query))

    def _get_health(self, path: str, query: Dict[str, list]) -> None:
        self._send_json(
            200,
            {
                "status": "ok",
                "service": "finops-cost-agent",
                "version": SERVICE_VERSION,
            },
        )

    def _get_catalog(self, path: str, query: Dict[str, list]) -> None:
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

    def _get_preset(self, path: str, query: Dict[str, list]) -> None:
        report = self.server.preset_cache.get(PERFOPS_PRESET_NAME)
        if report is None:  # pragma: no cover - seed_preset_audits always fills it
            report = build_preset_report(self.server.analyzer, persist=False)
        # GET is side-effect free: serve the startup cache, never touch SQLite.
        self._send_json(200, copy.deepcopy(report))

    def _get_audits(self, path: str, query: Dict[str, list]) -> None:
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

    def _post_analyze(self, path: str, query: Dict[str, list]) -> None:
        raw_body = self._read_request_body(self._body_limit_for(path))
        if raw_body is None:
            return
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
    api_token: Optional[str] = None,
    max_body_bytes: Optional[int] = None,
    max_bulk_body_bytes: Optional[int] = None,
) -> FinOpsHTTPServer:
    resolved_db = db_path or os.environ.get("FINOPS_DB_PATH", "finops_audit.db")
    analyzer = FinOpsAnalyzer(store=FinOpsAuditStore(resolved_db))
    return FinOpsHTTPServer(
        (host, port),
        FinOpsHTTPRequestHandler,
        analyzer=analyzer,
        api_token=api_token,
        max_body_bytes=max_body_bytes,
        max_bulk_body_bytes=max_bulk_body_bytes,
    )


def run_server(host: str = "0.0.0.0", port: int = 4030, db_path: Optional[str] = None) -> None:
    server = create_server(host=host, port=port, db_path=db_path)
    print(f"FinOps Cost Agent v{SERVICE_VERSION} listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
