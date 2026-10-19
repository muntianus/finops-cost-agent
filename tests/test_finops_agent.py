"""Comprehensive test suite for FinOps Cost Agent (analyzer, SQLite store, CLI, and HTTP API)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from finops_agent import (
    SKU_CATALOG,
    FinOpsAnalyzer,
    FinOpsAuditStore,
    RightsizingRecommendation,
    analyze_nat_egress,
    create_server,
    get_perfops_estate_preset,
)


class TestFinOpsAnalyzerMath(unittest.TestCase):
    def setUp(self) -> None:
        self.store = FinOpsAuditStore(":memory:")
        self.analyzer = FinOpsAnalyzer(store=self.store)

    def test_analyze_nat_egress_thresholds(self) -> None:
        low = analyze_nat_egress(500.0, rate_per_gb=0.045)
        self.assertEqual(low["estimated_monthly_usd"], 22.5)
        self.assertFalse(low["recommend_vpc_endpoint"])
        self.assertEqual(low["monthly_savings_usd"], 0.0)

        high = analyze_nat_egress(2000.0, rate_per_gb=0.045)
        self.assertEqual(high["estimated_monthly_usd"], 90.0)
        self.assertTrue(high["recommend_vpc_endpoint"])
        self.assertGreater(high["monthly_savings_usd"], 50.0)

    def test_aws_ec2_rightsizing_and_spot(self) -> None:
        rec = self.analyzer.analyze_workload(
            {
                "resource_id": "worker-ec2-01",
                "provider": "aws",
                "sku": "m6i.2xlarge",
                "cpu_p95_pct": 18.0,
                "mem_p95_pct": 24.0,
                "stateless": True,
                "migration_cost_usd": 10.0,
            }
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertIsInstance(rec, RightsizingRecommendation)
        self.assertEqual(rec.category, "RIGHTSIZE")
        self.assertIn("m6i.xlarge", rec.recommended_sku)
        self.assertIn("spot", rec.recommended_sku)
        self.assertEqual(rec.idle_waste_pct, 76.0)
        self.assertGreater(rec.monthly_savings_usd, 200.0)
        self.assertGreaterEqual(rec.payback_days, 1)

    def test_hostinger_vps_rightsizing_reserved(self) -> None:
        rec = self.analyzer.analyze_workload(
            {
                "resource_id": "vps-45.9.191.203",
                "provider": "hostinger",
                "sku": "kvm-8",
                "cpu_p95_pct": 28.0,
                "mem_p95_pct": 35.0,
                "steady_state": True,
            }
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.category, "RIGHTSIZE")
        self.assertIn("kvm-4", rec.recommended_sku)
        self.assertGreater(rec.monthly_savings_usd, 20.0)

    def test_docker_cgroup_memory_tuning_detection(self) -> None:
        rec = self.analyzer.analyze_workload(
            {
                "resource_id": "globex-backend-1",
                "provider": "docker",
                "type": "cgroup",
                "mem_limit_mb": 2048,
                "mem_p95_mb": 340,
                "cpu_limit_cores": 2.0,
                "cpu_p95_cores": 0.35,
            }
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.category, "CGROUP_TUNE")
        self.assertEqual(rec.resource_id, "globex-backend-1")
        self.assertIn("cgroup:512Mi", rec.recommended_sku)
        self.assertGreater(rec.monthly_savings_usd, 5.0)
        self.assertGreater(rec.idle_waste_pct, 80.0)

    def test_llm_token_cache_and_routing(self) -> None:
        rec = self.analyzer.analyze_llm_budget(
            {
                "resource_id": "agent-router",
                "model": "claude-sonnet-4.6",
                "target_fast_model": "gemini-2.5-flash",
                "monthly_input_tokens_m": 40.0,
                "monthly_output_tokens_m": 8.0,
                "current_cache_hit_ratio": 0.05,
                "target_cache_hit_ratio": 0.70,
                "routine_task_share": 0.65,
            }
        )
        self.assertIsNotNone(rec)
        assert rec is not None
        self.assertEqual(rec.category, "LLM_CACHE_ROUTING")
        self.assertGreater(rec.monthly_savings_usd, 150.0)
        self.assertIn("gemini-2.5-flash", rec.recommended_sku)

    def test_sqlite_persistence_file_and_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = os.path.join(tmpdir, "test_finops.db")
            store = FinOpsAuditStore(db_file)
            analyzer = FinOpsAnalyzer(store=store)
            preset = get_perfops_estate_preset()
            report = analyzer.analyze_estate(preset, persist=True, preset_name="perfops-estate")

            self.assertIn("audit_id", report)
            self.assertGreater(report["summary"]["total_annual_savings_usd"], 5000.0)
            self.assertGreater(report["summary"]["total_annual_savings_rub"], 400000.0)

            audits = store.list_audits()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0]["audit_id"], report["audit_id"])
            self.assertEqual(audits[0]["preset_name"], "perfops-estate")
            self.assertEqual(len(audits[0]["recommendations"]), report["summary"]["recommendation_count"])


class TestFinOpsHTTPServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Keep the shared server deterministic even if the developer shell exports these.
        cls._env_patch = patch.dict(
            os.environ,
            {
                "FINOPS_QUIET": "1",
                "FINOPS_API_TOKEN": "",
                "FINOPS_MAX_BODY_BYTES": "",
                "FINOPS_MAX_BULK_BODY_BYTES": "",
            },
        )
        cls._env_patch.start()
        cls.addClassCleanup(cls._env_patch.stop)
        cls.server = create_server(host="127.0.0.1", port=0, db_path=":memory:")
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2.0)

    def _get_json(self, path: str) -> dict:
        with urlopen(f"{self.base_url}{path}", timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            return json.loads(resp.read().decode("utf-8"))

    def test_health_endpoint(self) -> None:
        data = self._get_json("/health")
        self.assertEqual(
            data,
            {
                "status": "ok",
                "service": "finops-cost-agent",
                "version": "1.1.0",
            },
        )

    def test_catalog_skus_endpoint(self) -> None:
        data = self._get_json("/api/v1/catalog/skus")
        self.assertIn("aws", data["providers"])
        self.assertIn("gcp", data["providers"])
        self.assertIn("hostinger", data["providers"])
        self.assertIn("llm", data["providers"])
        self.assertIn("m6i.2xlarge", data["catalog"]["aws"])

        filtered = self._get_json("/api/v1/catalog/skus?provider=hostinger")
        self.assertEqual(filtered["providers"], ["hostinger"])
        self.assertIn("kvm-8", filtered["catalog"]["hostinger"])

    def test_analyze_endpoint_all_categories(self) -> None:
        payload = {
            "workloads": [
                {
                    "resource_id": "ec2-overprovisioned",
                    "provider": "aws",
                    "sku": "m6i.2xlarge",
                    "cpu_p95_pct": 19.0,
                    "mem_p95_pct": 25.0,
                    "stateless": True,
                },
                {
                    "resource_id": "ops-cadvisor",
                    "provider": "docker",
                    "type": "cgroup",
                    "mem_limit_mb": 1024,
                    "mem_p95_mb": 135,
                    "cpu_limit_cores": 1.0,
                    "cpu_p95_cores": 0.15,
                },
            ],
            "egress": [
                {
                    "resource_id": "nat-gw-eu",
                    "provider": "aws",
                    "gb_processed": 1800.0,
                    "rate_per_gb": 0.045,
                }
            ],
            "llm_usage": [
                {
                    "resource_id": "aco-llm-gateway",
                    "model": "claude-sonnet-4.6",
                    "monthly_input_tokens_m": 25.0,
                    "monthly_output_tokens_m": 5.0,
                }
            ],
        }
        report = self._post_json("/api/v1/analyze", payload)
        categories = {r["category"] for r in report["recommendations"]}
        self.assertEqual(
            categories,
            {"RIGHTSIZE", "CGROUP_TUNE", "NAT_ENDPOINT", "LLM_CACHE_ROUTING"},
        )
        self.assertGreater(report["summary"]["total_annual_savings_usd"], 4000.0)
        self.assertGreater(report["summary"]["total_annual_savings_rub"], 350000.0)

    def test_presets_perfops_estate_and_audits_endpoint(self) -> None:
        preset_report = self._get_json("/api/v1/presets/perfops-estate")
        self.assertEqual(preset_report["estate"]["vps_host"], "45.9.191.203")
        resources = {r["resource_id"] for r in preset_report["recommendations"]}
        self.assertIn("globex-backend-1", resources)
        self.assertIn("ops-grafana", resources)
        self.assertIn("ops-cadvisor", resources)

        audits_resp = self._get_json("/api/v1/audits")
        self.assertGreaterEqual(audits_resp["count"], 1)
        audit_ids = {a["audit_id"] for a in audits_resp["audits"]}
        self.assertIn(preset_report["audit_id"], audit_ids)

    def test_preset_get_is_read_only_and_cached(self) -> None:
        store = self.server.analyzer.store
        audits_before = store.count_audits()
        recommendations_before = store.count_recommendations()

        first = self._get_json("/api/v1/presets/perfops-estate")
        second = self._get_json("/api/v1/presets/perfops-estate")

        self.assertEqual(store.count_audits(), audits_before)
        self.assertEqual(store.count_recommendations(), recommendations_before)
        self.assertEqual(first["audit_id"], second["audit_id"])
        self.assertEqual(first["timestamp"], second["timestamp"])

        audits = self._get_json("/api/v1/audits")["audits"]
        self.assertIn(first["audit_id"], {a["audit_id"] for a in audits})

    def test_404_on_unknown_route(self) -> None:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(f"{self.base_url}/api/v1/nonexistent", timeout=5)
        try:
            self.assertEqual(ctx.exception.code, 404)
        finally:
            ctx.exception.close()


class TestFinOpsHTTPHardening(unittest.TestCase):
    """Body size limits and optional bearer authentication."""

    def setUp(self) -> None:
        self._env_patch = patch.dict(os.environ, {"FINOPS_QUIET": "1"})
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)
        self._servers = []

    def tearDown(self) -> None:
        for server, thread in self._servers:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2.0)

    def _start(self, **kwargs):
        server = create_server(host="127.0.0.1", port=0, db_path=":memory:", **kwargs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_address[1]}", server

    @staticmethod
    def _get_json(base_url: str, path: str, token: str = "") -> tuple:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with urlopen(Request(f"{base_url}{path}", headers=headers, method="GET"), timeout=5) as resp:
            return resp.status, resp.headers, json.loads(resp.read().decode("utf-8"))

    def _expect_http_error(self, request: Request) -> HTTPError:
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request, timeout=5)
        error = ctx.exception
        self.addCleanup(error.close)
        return error

    def test_oversized_bulk_body_returns_413(self) -> None:
        base_url, _ = self._start(max_bulk_body_bytes=1024)
        payload = b'{"workloads": []}' + b" " * 4096
        request = Request(
            f"{base_url}/api/v1/analyze",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        error = self._expect_http_error(request)
        self.assertEqual(error.code, 413)
        self.assertEqual(error.headers.get("Connection"), "close")
        body = json.loads(error.read().decode("utf-8"))
        self.assertEqual(body["error"], "payload_too_large")
        self.assertEqual(body["limit_bytes"], 1024)
        self.assertEqual(body["received_bytes"], len(payload))

    def test_body_within_bulk_limit_is_accepted(self) -> None:
        base_url, _ = self._start(max_bulk_body_bytes=4096)
        payload = json.dumps({"workloads": [], "persist": False}).encode("utf-8")
        request = Request(
            f"{base_url}/api/v1/analyze",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=5) as resp:
            self.assertEqual(resp.status, 200)
            self.assertEqual(json.loads(resp.read().decode("utf-8"))["summary"]["recommendation_count"], 0)

    def test_auth_required_when_token_configured(self) -> None:
        base_url, _ = self._start(api_token="secret-test-token")

        status, _, health = self._get_json(base_url, "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")

        error = self._expect_http_error(Request(f"{base_url}/api/v1/audits", method="GET"))
        self.assertEqual(error.code, 401)
        self.assertIn("Bearer", error.headers.get("WWW-Authenticate", ""))
        self.assertEqual(json.loads(error.read().decode("utf-8"))["error"], "unauthorized")

        error = self._expect_http_error(
            Request(
                f"{base_url}/api/v1/audits",
                headers={"Authorization": "Bearer wrong-token"},
                method="GET",
            )
        )
        self.assertEqual(error.code, 401)

        status, _, audits = self._get_json(base_url, "/api/v1/audits", token="secret-test-token")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(audits["count"], 1)

        error = self._expect_http_error(
            Request(
                f"{base_url}/api/v1/analyze",
                data=b'{"workloads": []}',
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        )
        self.assertEqual(error.code, 401)

    def test_auth_disabled_when_token_unset(self) -> None:
        with self.assertLogs("finops_service.server", level="WARNING") as logs:
            base_url, _ = self._start(api_token="")
        self.assertTrue(any("FINOPS_API_TOKEN" in line for line in logs.output))
        status, _, audits = self._get_json(base_url, "/api/v1/audits")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(audits["count"], 1)


if __name__ == "__main__":
    unittest.main()
