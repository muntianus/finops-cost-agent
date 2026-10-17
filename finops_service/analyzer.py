"""Core FinOps workload analyzer, pricing catalog, and SQLite audit store."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

USD_TO_RUB_RATE = 96.5

SKU_CATALOG: Dict[str, Dict[str, Dict[str, Any]]] = {
    "aws": {
        "m6i.2xlarge": {
            "provider": "aws",
            "service": "ec2",
            "vcpu": 8,
            "memory_gb": 32.0,
            "monthly_usd": 280.32,
            "downsize_to": "m6i.xlarge",
            "reserved_1y_discount": 0.36,
            "spot_discount": 0.68,
        },
        "m6i.xlarge": {
            "provider": "aws",
            "service": "ec2",
            "vcpu": 4,
            "memory_gb": 16.0,
            "monthly_usd": 140.16,
            "downsize_to": "m6i.large",
            "reserved_1y_discount": 0.36,
            "spot_discount": 0.68,
        },
        "m6i.large": {
            "provider": "aws",
            "service": "ec2",
            "vcpu": 2,
            "memory_gb": 8.0,
            "monthly_usd": 70.08,
            "downsize_to": "t3.medium",
            "reserved_1y_discount": 0.35,
            "spot_discount": 0.65,
        },
        "t3.medium": {
            "provider": "aws",
            "service": "ec2",
            "vcpu": 2,
            "memory_gb": 4.0,
            "monthly_usd": 30.37,
            "downsize_to": "t3.small",
            "reserved_1y_discount": 0.34,
            "spot_discount": 0.65,
        },
        "t3.small": {
            "provider": "aws",
            "service": "ec2",
            "vcpu": 2,
            "memory_gb": 2.0,
            "monthly_usd": 15.18,
            "downsize_to": None,
            "reserved_1y_discount": 0.34,
            "spot_discount": 0.65,
        },
        "db.r6g.xlarge": {
            "provider": "aws",
            "service": "rds",
            "vcpu": 4,
            "memory_gb": 32.0,
            "monthly_usd": 345.00,
            "downsize_to": "db.r6g.large",
            "reserved_1y_discount": 0.38,
            "spot_discount": 0.0,
        },
        "db.r6g.large": {
            "provider": "aws",
            "service": "rds",
            "vcpu": 2,
            "memory_gb": 16.0,
            "monthly_usd": 172.50,
            "downsize_to": "db.t4g.medium",
            "reserved_1y_discount": 0.38,
            "spot_discount": 0.0,
        },
        "db.t4g.medium": {
            "provider": "aws",
            "service": "rds",
            "vcpu": 2,
            "memory_gb": 4.0,
            "monthly_usd": 52.56,
            "downsize_to": None,
            "reserved_1y_discount": 0.35,
            "spot_discount": 0.0,
        },
        "nat-gateway": {
            "provider": "aws",
            "service": "vpc-nat",
            "vcpu": 0,
            "memory_gb": 0.0,
            "monthly_usd": 32.85,
            "rate_per_gb_usd": 0.045,
            "downsize_to": "vpc-gateway-endpoint",
        },
    },
    "gcp": {
        "e2-standard-8": {
            "provider": "gcp",
            "service": "gke",
            "vcpu": 8,
            "memory_gb": 32.0,
            "monthly_usd": 195.65,
            "downsize_to": "e2-standard-4",
            "reserved_1y_discount": 0.37,
            "spot_discount": 0.69,
        },
        "e2-standard-4": {
            "provider": "gcp",
            "service": "gke",
            "vcpu": 4,
            "memory_gb": 16.0,
            "monthly_usd": 97.83,
            "downsize_to": "e2-standard-2",
            "reserved_1y_discount": 0.37,
            "spot_discount": 0.69,
        },
        "e2-standard-2": {
            "provider": "gcp",
            "service": "gke",
            "vcpu": 2,
            "memory_gb": 8.0,
            "monthly_usd": 48.91,
            "downsize_to": "e2-medium",
            "reserved_1y_discount": 0.37,
            "spot_discount": 0.65,
        },
        "e2-medium": {
            "provider": "gcp",
            "service": "gke",
            "vcpu": 2,
            "memory_gb": 4.0,
            "monthly_usd": 24.46,
            "downsize_to": None,
            "reserved_1y_discount": 0.37,
            "spot_discount": 0.65,
        },
        "cloud-run-2vcpu-4gb": {
            "provider": "gcp",
            "service": "cloud-run",
            "vcpu": 2,
            "memory_gb": 4.0,
            "monthly_usd": 68.40,
            "downsize_to": "cloud-run-1vcpu-2gb",
            "reserved_1y_discount": 0.17,
            "spot_discount": 0.0,
        },
        "cloud-run-1vcpu-2gb": {
            "provider": "gcp",
            "service": "cloud-run",
            "vcpu": 1,
            "memory_gb": 2.0,
            "monthly_usd": 34.20,
            "downsize_to": None,
            "reserved_1y_discount": 0.17,
            "spot_discount": 0.0,
        },
        "bigquery-on-demand-10tb": {
            "provider": "gcp",
            "service": "bigquery",
            "vcpu": 0,
            "memory_gb": 0.0,
            "monthly_usd": 62.50,
            "downsize_to": "bigquery-partitioned-clustered",
            "reserved_1y_discount": 0.25,
            "spot_discount": 0.0,
        },
    },
    "hostinger": {
        "kvm-8": {
            "provider": "hostinger",
            "service": "vps",
            "vcpu": 8,
            "memory_gb": 32.0,
            "monthly_usd": 39.99,
            "downsize_to": "kvm-4",
            "reserved_1y_discount": 0.25,
            "spot_discount": 0.0,
        },
        "kvm-4": {
            "provider": "hostinger",
            "service": "vps",
            "vcpu": 4,
            "memory_gb": 16.0,
            "monthly_usd": 19.99,
            "downsize_to": "kvm-2",
            "reserved_1y_discount": 0.25,
            "spot_discount": 0.0,
        },
        "kvm-2": {
            "provider": "hostinger",
            "service": "vps",
            "vcpu": 2,
            "memory_gb": 8.0,
            "monthly_usd": 11.99,
            "downsize_to": "kvm-1",
            "reserved_1y_discount": 0.20,
            "spot_discount": 0.0,
        },
        "kvm-1": {
            "provider": "hostinger",
            "service": "vps",
            "vcpu": 1,
            "memory_gb": 4.0,
            "monthly_usd": 6.99,
            "downsize_to": None,
            "reserved_1y_discount": 0.20,
            "spot_discount": 0.0,
        },
    },
    "docker": {
        "cgroup-container": {
            "provider": "docker",
            "service": "container",
            "cost_per_gb_month_usd": 2.50,
            "cost_per_vcpu_month_usd": 4.00,
        }
    },
    "llm": {
        "claude-sonnet-4.6": {
            "provider": "anthropic",
            "input_per_1m_usd": 3.00,
            "output_per_1m_usd": 15.00,
            "cached_input_per_1m_usd": 0.30,
            "route_downsize_to": "gemini-2.5-flash",
        },
        "gpt-4o": {
            "provider": "openai",
            "input_per_1m_usd": 2.50,
            "output_per_1m_usd": 10.00,
            "cached_input_per_1m_usd": 1.25,
            "route_downsize_to": "gemini-2.5-flash",
        },
        "gemini-2.5-pro": {
            "provider": "google",
            "input_per_1m_usd": 1.25,
            "output_per_1m_usd": 10.00,
            "cached_input_per_1m_usd": 0.31,
            "route_downsize_to": "gemini-2.5-flash",
        },
        "gemini-2.5-flash": {
            "provider": "google",
            "input_per_1m_usd": 0.15,
            "output_per_1m_usd": 0.60,
            "cached_input_per_1m_usd": 0.0375,
            "route_downsize_to": None,
        },
    },
}


@dataclass
class RightsizingRecommendation:
    resource_id: str
    current_sku: str
    recommended_sku: str
    monthly_savings_usd: float
    category: str = "RIGHTSIZE"
    provider: str = "aws"
    current_monthly_usd: float = 0.0
    recommended_monthly_usd: float = 0.0
    idle_waste_pct: float = 0.0
    purchase_option: str = "on-demand"
    payback_days: int = 1
    rationale: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["annual_savings_usd"] = round(self.monthly_savings_usd * 12.0, 2)
        data["annual_savings_rub"] = round(self.monthly_savings_usd * 12.0 * USD_TO_RUB_RATE, 2)
        return data


def analyze_nat_egress(
    gb_processed: float,
    rate_per_gb: float = 0.045,
    base_monthly_usd: float = 0.0,
    s3_dynamodb_share: float = 0.65,
) -> Dict[str, Any]:
    """Calculate NAT Gateway egress spend and VPC Gateway Endpoint savings."""
    data_cost = gb_processed * rate_per_gb
    monthly_cost = data_cost + base_monthly_usd
    recommend_endpoint = monthly_cost > 50.0
    offloadable_gb = gb_processed * s3_dynamodb_share if recommend_endpoint else 0.0
    monthly_savings = round(offloadable_gb * rate_per_gb, 2)
    return {
        "gb_processed": gb_processed,
        "rate_per_gb": rate_per_gb,
        "estimated_monthly_usd": round(monthly_cost, 2),
        "recommend_vpc_endpoint": recommend_endpoint,
        "offloadable_gb": round(offloadable_gb, 2),
        "monthly_savings_usd": monthly_savings,
        "annual_savings_usd": round(monthly_savings * 12.0, 2),
    }


def _lookup_sku(sku: str, provider: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if provider and provider in SKU_CATALOG and sku in SKU_CATALOG[provider]:
        return SKU_CATALOG[provider][sku]
    for prov_map in SKU_CATALOG.values():
        if isinstance(prov_map, dict) and sku in prov_map:
            return prov_map[sku]
    return None


class FinOpsAuditStore:
    """SQLite persistence layer for FinOps audits and itemized recommendations."""

    def __init__(self, db_path: str = "finops_audit.db") -> None:
        self.db_path = db_path
        self._shared_conn: Optional[sqlite3.Connection] = None
        if db_path == ":memory:":
            self._shared_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS finops_audits (
                    audit_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    preset_name TEXT,
                    total_monthly_spend_usd REAL NOT NULL,
                    total_monthly_savings_usd REAL NOT NULL,
                    total_annual_savings_usd REAL NOT NULL,
                    total_annual_savings_rub REAL NOT NULL,
                    recommendation_count INTEGER NOT NULL,
                    summary_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS finops_recommendations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    current_sku TEXT NOT NULL,
                    recommended_sku TEXT NOT NULL,
                    monthly_savings_usd REAL NOT NULL,
                    idle_waste_pct REAL NOT NULL,
                    payback_days INTEGER NOT NULL,
                    rationale TEXT NOT NULL,
                    FOREIGN KEY(audit_id) REFERENCES finops_audits(audit_id)
                );
                """
            )
            conn.commit()
        finally:
            if self._shared_conn is None:
                conn.close()

    def save_audit(self, report: Dict[str, Any], preset_name: Optional[str] = None) -> str:
        audit_id = report.get("audit_id") or f"audit-{uuid.uuid4().hex[:10]}"
        created_at = report.get("timestamp") or datetime.now(timezone.utc).isoformat()
        summary = report.get("summary", {})
        recommendations = report.get("recommendations", [])

        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO finops_audits (
                    audit_id, created_at, preset_name,
                    total_monthly_spend_usd, total_monthly_savings_usd,
                    total_annual_savings_usd, total_annual_savings_rub,
                    recommendation_count, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    audit_id,
                    created_at,
                    preset_name,
                    float(summary.get("total_monthly_spend_usd", 0.0)),
                    float(summary.get("total_monthly_savings_usd", 0.0)),
                    float(summary.get("total_annual_savings_usd", 0.0)),
                    float(summary.get("total_annual_savings_rub", 0.0)),
                    len(recommendations),
                    json.dumps(summary),
                ),
            )
            conn.execute("DELETE FROM finops_recommendations WHERE audit_id = ?", (audit_id,))
            for rec in recommendations:
                conn.execute(
                    """
                    INSERT INTO finops_recommendations (
                        audit_id, resource_id, category, provider,
                        current_sku, recommended_sku, monthly_savings_usd,
                        idle_waste_pct, payback_days, rationale
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        audit_id,
                        rec["resource_id"],
                        rec["category"],
                        rec.get("provider", "unknown"),
                        rec["current_sku"],
                        rec["recommended_sku"],
                        float(rec["monthly_savings_usd"]),
                        float(rec.get("idle_waste_pct", 0.0)),
                        int(rec.get("payback_days", 1)),
                        rec.get("rationale", ""),
                    ),
                )
            conn.commit()
            return audit_id
        finally:
            if self._shared_conn is None:
                conn.close()

    def list_audits(self, limit: int = 25) -> List[Dict[str, Any]]:
        conn = self._connect()
        try:
            cursor = conn.execute(
                """
                SELECT audit_id, created_at, preset_name,
                       total_monthly_spend_usd, total_monthly_savings_usd,
                       total_annual_savings_usd, total_annual_savings_rub,
                       recommendation_count, summary_json
                FROM finops_audits
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            result: List[Dict[str, Any]] = []
            for row in rows:
                rec_cursor = conn.execute(
                    """
                    SELECT resource_id, category, provider, current_sku,
                           recommended_sku, monthly_savings_usd, idle_waste_pct,
                           payback_days, rationale
                    FROM finops_recommendations
                    WHERE audit_id = ?
                    ORDER BY monthly_savings_usd DESC
                    """,
                    (row["audit_id"],),
                )
                recs = [dict(r) for r in rec_cursor.fetchall()]
                result.append(
                    {
                        "audit_id": row["audit_id"],
                        "created_at": row["created_at"],
                        "preset_name": row["preset_name"],
                        "total_monthly_spend_usd": row["total_monthly_spend_usd"],
                        "total_monthly_savings_usd": row["total_monthly_savings_usd"],
                        "total_annual_savings_usd": row["total_annual_savings_usd"],
                        "total_annual_savings_rub": row["total_annual_savings_rub"],
                        "recommendation_count": row["recommendation_count"],
                        "summary": json.loads(row["summary_json"]),
                        "recommendations": recs,
                    }
                )
            return result
        finally:
            if self._shared_conn is None:
                conn.close()


class FinOpsAnalyzer:
    """Engine for cloud rightsizing, Docker cgroup tuning, NAT egress, and LLM token routing."""

    def __init__(self, store: Optional[FinOpsAuditStore] = None, usd_to_rub: float = USD_TO_RUB_RATE) -> None:
        self.store = store or FinOpsAuditStore(":memory:")
        self.usd_to_rub = usd_to_rub

    def analyze_workload(self, workload: Dict[str, Any]) -> Optional[RightsizingRecommendation]:
        resource_id = str(workload.get("resource_id", "unknown-resource"))
        provider = str(workload.get("provider", "aws")).lower()
        wtype = str(workload.get("type", "")).lower()

        # Docker cgroup container analysis
        if provider == "docker" or wtype in ("cgroup", "container", "docker"):
            return self._analyze_docker_cgroup(workload)

        sku_name = str(workload.get("sku", "m6i.xlarge"))
        sku_info = _lookup_sku(sku_name, provider)
        current_monthly = float(
            workload.get("monthly_cost_usd")
            or (sku_info["monthly_usd"] if sku_info and "monthly_usd" in sku_info else 100.0)
        )

        cpu_p95 = float(workload.get("cpu_p95_pct", workload.get("cpu_util_pct", 25.0)))
        mem_p95 = float(workload.get("mem_p95_pct", workload.get("mem_util_pct", 35.0)))
        peak_util = max(cpu_p95, mem_p95)
        idle_waste_pct = round(max(0.0, 100.0 - peak_util), 1)
        is_stateless = bool(workload.get("stateless", False))
        steady_state = bool(workload.get("steady_state", True))

        # BigQuery on-demand optimization
        if sku_info and sku_info.get("service") == "bigquery":
            tb_scanned = float(workload.get("monthly_tb_scanned", 10.0))
            current_monthly = round(tb_scanned * 6.25, 2)
            rec_monthly = round(current_monthly * 0.45, 2)
            savings = round(current_monthly - rec_monthly, 2)
            return RightsizingRecommendation(
                resource_id=resource_id,
                current_sku=sku_name,
                recommended_sku="bigquery-partitioned-clustered+bi-engine",
                monthly_savings_usd=savings,
                category="RIGHTSIZE",
                provider="gcp",
                current_monthly_usd=current_monthly,
                recommended_monthly_usd=rec_monthly,
                idle_waste_pct=55.0,
                purchase_option="partition-cluster",
                payback_days=2,
                rationale=(
                    f"BigQuery scanning {tb_scanned} TB/mo on-demand; partitioning by date + clustering "
                    "cuts scanned bytes by ~55%."
                ),
            )

        target_sku_name = sku_name
        target_monthly = current_monthly

        # Downsize SKU if P95 CPU & Memory utilization are both under 42%
        if cpu_p95 < 42.0 and mem_p95 < 45.0:
            downsize_sku = (
                workload.get("recommended_sku")
                or (sku_info.get("downsize_to") if sku_info else None)
            )
            if downsize_sku:
                down_info = _lookup_sku(downsize_sku, provider)
                target_sku_name = downsize_sku
                target_monthly = float(
                    down_info["monthly_usd"] if down_info and "monthly_usd" in down_info else current_monthly * 0.5
                )

        # Evaluate Spot vs Reserved Instance discount on the rightsized SKU
        target_info = _lookup_sku(target_sku_name, provider) or sku_info or {}
        purchase_option = "on-demand"
        if is_stateless and float(target_info.get("spot_discount", 0.0)) > 0:
            discount = float(target_info["spot_discount"])
            target_monthly = round(target_monthly * (1.0 - discount), 2)
            purchase_option = "spot"
        elif steady_state and float(target_info.get("reserved_1y_discount", 0.0)) > 0 and cpu_p95 >= 20.0:
            discount = float(target_info["reserved_1y_discount"])
            target_monthly = round(target_monthly * (1.0 - discount), 2)
            purchase_option = "reserved-1y"

        savings = round(max(0.0, current_monthly - target_monthly), 2)
        if savings <= 0.50:
            return None

        engineering_effort_usd = float(workload.get("migration_cost_usd", 12.0))
        daily_savings = savings / 30.0
        payback_days = max(1, int(round(engineering_effort_usd / daily_savings))) if daily_savings > 0 else 1

        rec_label = target_sku_name if purchase_option == "on-demand" else f"{target_sku_name} ({purchase_option})"
        rationale = (
            f"P95 CPU {cpu_p95:.1f}% / Mem {mem_p95:.1f}% (idle waste {idle_waste_pct:.1f}%). "
            f"Transition {sku_name} -> {rec_label} saves ${savings:.2f}/mo (payback {payback_days}d)."
        )

        return RightsizingRecommendation(
            resource_id=resource_id,
            current_sku=sku_name,
            recommended_sku=rec_label,
            monthly_savings_usd=savings,
            category="RIGHTSIZE",
            provider=provider,
            current_monthly_usd=round(current_monthly, 2),
            recommended_monthly_usd=round(target_monthly, 2),
            idle_waste_pct=idle_waste_pct,
            purchase_option=purchase_option,
            payback_days=payback_days,
            rationale=rationale,
            metadata={
                "cpu_p95_pct": cpu_p95,
                "mem_p95_pct": mem_p95,
                "stateless": is_stateless,
            },
        )

    def _analyze_docker_cgroup(self, workload: Dict[str, Any]) -> Optional[RightsizingRecommendation]:
        container_name = str(workload.get("resource_id") or workload.get("container") or "docker-container")
        mem_limit_mb = float(workload.get("mem_limit_mb", 2048.0))
        mem_p95_mb = float(workload.get("mem_p95_mb", workload.get("mem_rss_mb", 320.0)))
        cpu_limit_cores = float(workload.get("cpu_limit_cores", 2.0))
        cpu_p95_cores = float(workload.get("cpu_p95_cores", 0.25))

        # Target 1.45x headroom above P95 RSS, rounded to 64MB increments (min 128MB)
        raw_target_mb = max(128.0, mem_p95_mb * 1.45)
        recommended_mem_mb = int(((raw_target_mb + 63) // 64) * 64)
        recommended_cpu = round(max(0.25, min(cpu_limit_cores, cpu_p95_cores * 1.6)), 2)

        if recommended_mem_mb >= mem_limit_mb * 0.85 and recommended_cpu >= cpu_limit_cores * 0.85:
            return None

        mem_reclaimed_gb = max(0.0, (mem_limit_mb - recommended_mem_mb) / 1024.0)
        cpu_reclaimed = max(0.0, cpu_limit_cores - recommended_cpu)

        docker_rates = SKU_CATALOG["docker"]["cgroup-container"]
        current_cost = round(
            (mem_limit_mb / 1024.0) * docker_rates["cost_per_gb_month_usd"]
            + cpu_limit_cores * docker_rates["cost_per_vcpu_month_usd"],
            2,
        )
        savings = round(
            mem_reclaimed_gb * docker_rates["cost_per_gb_month_usd"]
            + cpu_reclaimed * docker_rates["cost_per_vcpu_month_usd"],
            2,
        )
        if savings <= 0.25:
            return None

        idle_waste_pct = round(max(0.0, (1.0 - (mem_p95_mb / max(1.0, mem_limit_mb))) * 100.0), 1)
        current_sku = f"cgroup:{int(mem_limit_mb)}Mi/{cpu_limit_cores:g}vCPU"
        recommended_sku = f"cgroup:{recommended_mem_mb}Mi/{recommended_cpu:g}vCPU"

        return RightsizingRecommendation(
            resource_id=container_name,
            current_sku=current_sku,
            recommended_sku=recommended_sku,
            monthly_savings_usd=savings,
            category="CGROUP_TUNE",
            provider="docker",
            current_monthly_usd=current_cost,
            recommended_monthly_usd=round(max(0.5, current_cost - savings), 2),
            idle_waste_pct=idle_waste_pct,
            purchase_option="cgroup-v2-limit",
            payback_days=1,
            rationale=(
                f"Container {container_name} uses {mem_p95_mb:.0f}Mi P95 of {mem_limit_mb:.0f}Mi limit "
                f"({idle_waste_pct:.1f}% slack). Cap memory_limit={recommended_mem_mb}m & cpus={recommended_cpu:g} "
                f"to reclaim {mem_reclaimed_gb:.2f} GiB on host VPS."
            ),
            metadata={
                "mem_limit_mb": mem_limit_mb,
                "mem_p95_mb": mem_p95_mb,
                "recommended_mem_mb": recommended_mem_mb,
                "recommended_cpu_cores": recommended_cpu,
            },
        )

    def analyze_egress_item(self, egress: Dict[str, Any]) -> Optional[RightsizingRecommendation]:
        resource_id = str(egress.get("resource_id", "nat-gateway-primary"))
        provider = str(egress.get("provider", "aws")).lower()
        gb_processed = float(egress.get("gb_processed", 0.0))
        rate_per_gb = float(egress.get("rate_per_gb", 0.045))
        base_monthly = float(egress.get("base_monthly_usd", 32.85 if provider == "aws" else 0.0))
        s3_share = float(egress.get("offloadable_share", 0.65))

        nat_res = analyze_nat_egress(
            gb_processed=gb_processed,
            rate_per_gb=rate_per_gb,
            base_monthly_usd=base_monthly,
            s3_dynamodb_share=s3_share,
        )
        if not nat_res["recommend_vpc_endpoint"] or nat_res["monthly_savings_usd"] <= 0:
            return None

        savings = nat_res["monthly_savings_usd"]
        current_usd = nat_res["estimated_monthly_usd"]
        return RightsizingRecommendation(
            resource_id=resource_id,
            current_sku=f"nat-gateway ({gb_processed:g} GB/mo)",
            recommended_sku="vpc-gateway-endpoint + cloudflare-r2-egress",
            monthly_savings_usd=savings,
            category="NAT_ENDPOINT",
            provider=provider,
            current_monthly_usd=current_usd,
            recommended_monthly_usd=round(current_usd - savings, 2),
            idle_waste_pct=round(s3_share * 100.0, 1),
            purchase_option="vpc-endpoint",
            payback_days=1,
            rationale=(
                f"NAT Gateway processes {gb_processed:g} GB/mo (${current_usd:.2f}/mo). "
                f"Routing {s3_share * 100:.0f}% registry/S3 traffic via free VPC Gateway Endpoint saves ${savings:.2f}/mo."
            ),
            metadata=nat_res,
        )

    def analyze_llm_budget(self, llm_usage: Dict[str, Any]) -> Optional[RightsizingRecommendation]:
        resource_id = str(llm_usage.get("resource_id", "llm-agent-router"))
        model = str(llm_usage.get("model", "claude-sonnet-4.6"))
        input_m = float(llm_usage.get("monthly_input_tokens_m", 0.0))
        output_m = float(llm_usage.get("monthly_output_tokens_m", 0.0))
        cache_hit_ratio = float(llm_usage.get("current_cache_hit_ratio", 0.05))
        target_cache_ratio = float(llm_usage.get("target_cache_hit_ratio", 0.65))
        flash_route_share = float(llm_usage.get("routine_task_share", 0.60))

        model_info = SKU_CATALOG["llm"].get(model, SKU_CATALOG["llm"]["claude-sonnet-4.6"])
        target_model = str(llm_usage.get("target_fast_model") or model_info.get("route_downsize_to") or "gemini-2.5-flash")
        fast_info = SKU_CATALOG["llm"].get(target_model, SKU_CATALOG["llm"]["gemini-2.5-flash"])

        current_input_cost = (
            input_m * (1.0 - cache_hit_ratio) * model_info["input_per_1m_usd"]
            + input_m * cache_hit_ratio * model_info["cached_input_per_1m_usd"]
        )
        current_output_cost = output_m * model_info["output_per_1m_usd"]
        current_monthly = round(current_input_cost + current_output_cost, 2)
        if current_monthly <= 1.0:
            return None

        # Optimized: route routine tasks to flash_lite/flash and apply prompt/response caching on remaining premium calls
        premium_share = 1.0 - flash_route_share
        opt_premium_in = (
            input_m
            * premium_share
            * (
                (1.0 - target_cache_ratio) * model_info["input_per_1m_usd"]
                + target_cache_ratio * model_info["cached_input_per_1m_usd"]
            )
        )
        opt_premium_out = output_m * premium_share * model_info["output_per_1m_usd"]

        opt_fast_in = (
            input_m
            * flash_route_share
            * (
                (1.0 - target_cache_ratio) * fast_info["input_per_1m_usd"]
                + target_cache_ratio * fast_info["cached_input_per_1m_usd"]
            )
        )
        opt_fast_out = output_m * flash_route_share * fast_info["output_per_1m_usd"]

        recommended_monthly = round(opt_premium_in + opt_premium_out + opt_fast_in + opt_fast_out, 2)
        savings = round(max(0.0, current_monthly - recommended_monthly), 2)
        if savings <= 0.50:
            return None

        waste_pct = round((savings / current_monthly) * 100.0, 1)
        return RightsizingRecommendation(
            resource_id=resource_id,
            current_sku=f"{model} ({input_m:g}M in / {output_m:g}M out)",
            recommended_sku=f"tiered:{model}+{target_model}+prompt-cache({int(target_cache_ratio*100)}%)",
            monthly_savings_usd=savings,
            category="LLM_CACHE_ROUTING",
            provider=str(model_info.get("provider", "anthropic")),
            current_monthly_usd=current_monthly,
            recommended_monthly_usd=recommended_monthly,
            idle_waste_pct=waste_pct,
            purchase_option="semantic-cache+model-router",
            payback_days=1,
            rationale=(
                f"Routing {int(flash_route_share*100)}% routine agent tasks from {model} to {target_model} "
                f"and raising prompt cache hit rate {int(cache_hit_ratio*100)}% -> {int(target_cache_ratio*100)}% "
                f"reduces token spend by ${savings:.2f}/mo ({waste_pct:.1f}%)."
            ),
            metadata={
                "model": model,
                "target_fast_model": target_model,
                "monthly_input_tokens_m": input_m,
                "monthly_output_tokens_m": output_m,
            },
        )

    def analyze_estate(
        self,
        payload: Dict[str, Any],
        persist: bool = True,
        preset_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        workloads = payload.get("workloads", [])
        egress_items = payload.get("egress", [])
        if isinstance(egress_items, dict):
            egress_items = [egress_items]
        llm_items = payload.get("llm_usage", [])
        if isinstance(llm_items, dict):
            llm_items = [llm_items]

        recommendations: List[RightsizingRecommendation] = []
        total_current_spend = 0.0

        for w in workloads:
            rec = self.analyze_workload(w)
            if rec:
                recommendations.append(rec)
                total_current_spend += rec.current_monthly_usd
            else:
                sku_info = _lookup_sku(str(w.get("sku", "")), str(w.get("provider", "")).lower())
                total_current_spend += float(
                    w.get("monthly_cost_usd") or (sku_info.get("monthly_usd", 0.0) if sku_info else 0.0)
                )

        for eg in egress_items:
            rec = self.analyze_egress_item(eg)
            if rec:
                recommendations.append(rec)
                total_current_spend += rec.current_monthly_usd
            else:
                nat_eval = analyze_nat_egress(
                    float(eg.get("gb_processed", 0.0)),
                    float(eg.get("rate_per_gb", 0.045)),
                    float(eg.get("base_monthly_usd", 0.0)),
                )
                total_current_spend += nat_eval["estimated_monthly_usd"]

        for llm in llm_items:
            rec = self.analyze_llm_budget(llm)
            if rec:
                recommendations.append(rec)
                total_current_spend += rec.current_monthly_usd

        recommendations.sort(key=lambda r: r.monthly_savings_usd, reverse=True)
        total_monthly_savings = round(sum(r.monthly_savings_usd for r in recommendations), 2)
        total_annual_savings_usd = round(total_monthly_savings * 12.0, 2)
        total_annual_savings_rub = round(total_annual_savings_usd * self.usd_to_rub, 2)
        total_current_spend = round(total_current_spend, 2)

        by_category: Dict[str, float] = {}
        for r in recommendations:
            by_category[r.category] = round(by_category.get(r.category, 0.0) + r.monthly_savings_usd, 2)

        audit_id = f"audit-{uuid.uuid4().hex[:10]}"
        timestamp = datetime.now(timezone.utc).isoformat()

        summary = {
            "total_monthly_spend_usd": total_current_spend,
            "optimized_monthly_spend_usd": round(max(0.0, total_current_spend - total_monthly_savings), 2),
            "total_monthly_savings_usd": total_monthly_savings,
            "total_annual_savings_usd": total_annual_savings_usd,
            "total_annual_savings_rub": total_annual_savings_rub,
            "usd_to_rub_rate": self.usd_to_rub,
            "savings_pct": round((total_monthly_savings / total_current_spend * 100.0), 1)
            if total_current_spend > 0
            else 0.0,
            "savings_by_category_usd": by_category,
            "recommendation_count": len(recommendations),
            "integrations": {
                "opencost_compatible": True,
                "infracost_compatible": True,
                "aco_endpoint": "https://aco.perfops.shop",
                "globex_api": "https://api.globlex.pro",
            },
        }

        report = {
            "audit_id": audit_id,
            "timestamp": timestamp,
            "preset": preset_name,
            "summary": summary,
            "recommendations": [r.to_dict() for r in recommendations],
        }

        if persist and self.store is not None:
            self.store.save_audit(report, preset_name=preset_name)

        return report


def get_perfops_estate_preset() -> Dict[str, Any]:
    """Return realistic production workload telemetry for PerfOps & Globlex estate (VPS 45.9.191.203 + Cloud + AI)."""
    return {
        "estate_name": "perfops-globex-production",
        "vps_host": "45.9.191.203",
        "workloads": [
            {
                "resource_id": "vps-45.9.191.203-hostinger",
                "provider": "hostinger",
                "sku": "kvm-8",
                "cpu_p95_pct": 28.5,
                "mem_p95_pct": 38.0,
                "steady_state": True,
                "migration_cost_usd": 5.0,
            },
            {
                "resource_id": "globex-backend-1",
                "provider": "docker",
                "type": "cgroup",
                "mem_limit_mb": 2048,
                "mem_p95_mb": 340,
                "cpu_limit_cores": 2.0,
                "cpu_p95_cores": 0.35,
            },
            {
                "resource_id": "ops-grafana",
                "provider": "docker",
                "type": "cgroup",
                "mem_limit_mb": 1024,
                "mem_p95_mb": 165,
                "cpu_limit_cores": 1.0,
                "cpu_p95_cores": 0.15,
            },
            {
                "resource_id": "ops-cadvisor",
                "provider": "docker",
                "type": "cgroup",
                "mem_limit_mb": 1024,
                "mem_p95_mb": 140,
                "cpu_limit_cores": 1.0,
                "cpu_p95_cores": 0.20,
            },
            {
                "resource_id": "aco-perfops-worker-pool",
                "provider": "aws",
                "sku": "m6i.2xlarge",
                "cpu_p95_pct": 22.0,
                "mem_p95_pct": 31.0,
                "stateless": True,
                "migration_cost_usd": 15.0,
            },
            {
                "resource_id": "globex-analytics-gke",
                "provider": "gcp",
                "sku": "e2-standard-8",
                "cpu_p95_pct": 31.0,
                "mem_p95_pct": 36.0,
                "steady_state": True,
                "migration_cost_usd": 12.0,
            },
        ],
        "egress": [
            {
                "resource_id": "aws-eu-central-1-nat-gw",
                "provider": "aws",
                "gb_processed": 2400.0,
                "rate_per_gb": 0.045,
                "base_monthly_usd": 32.85,
                "offloadable_share": 0.70,
            }
        ],
        "llm_usage": [
            {
                "resource_id": "perfops-multi-agent-router",
                "model": "claude-sonnet-4.6",
                "target_fast_model": "gemini-2.5-flash",
                "monthly_input_tokens_m": 45.0,
                "monthly_output_tokens_m": 9.0,
                "current_cache_hit_ratio": 0.10,
                "target_cache_hit_ratio": 0.70,
                "routine_task_share": 0.65,
            }
        ],
    }
