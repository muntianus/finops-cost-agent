# FinOps Cost Agent (`finops-cost-agent`)

Autonomous, zero-dependency Python 3 FinOps cloud, VPS, Docker cgroup, and LLM token cost analyzer & HTTP microservice. Built for the PerfOps & Globlex platform (`aco.perfops.shop`, `api.globlex.pro`, OpenCost, and Infracost pipelines).

## Features

- **Cloud & VPS Workload Rightsizing (`RIGHTSIZE`)**: Evaluates AWS EC2/RDS, GCP GKE/Cloud Run/BigQuery, and Hostinger KVM VPS telemetry (`cpu_p95_pct`, `mem_p95_pct`), recommending target SKUs, Spot vs. 1-year Reserved Instance discounts, idle waste %, and engineering ROI payback days.
- **Docker Cgroup v2 Memory & CPU Tuning (`CGROUP_TUNE`)**: Detects over-allocated container memory/CPU limits on production VPS nodes (`45.9.191.203` — `globex-backend-1`, `ops-grafana`, `ops-cadvisor`) and calculates safe 1.45x P95 RSS headroom caps.
- **NAT Gateway & Egress Optimization (`NAT_ENDPOINT`)**: Calculates monthly NAT data processing fees and models savings from offloading S3/DynamoDB/registry traffic to free VPC Gateway Endpoints and Cloudflare R2.
- **LLM Token Caching & Model Routing (`LLM_CACHE_ROUTING`)**: Analyzes multi-agent token budgets (`claude-sonnet-4.6`, `gpt-4o`, `gemini-2.5-pro`) and quantifies savings from semantic/prompt caching plus routing routine tasks to `gemini-2.5-flash`.
- **SQLite Audit Persistence**: Stores audit runs and itemized recommendations in `finops_audit.db` (or `:memory:`). Built-in presets are seeded once at startup (or via `seed-presets`), never from a `GET` request.

## Quick Start

### Run CLI Audit (PerfOps Production Estate Preset)

```bash
python3 finops_agent.py audit --preset perfops-estate --db :memory:
```

### Start HTTP Microservice (Default Port `4030`)

```bash
python3 finops_agent.py serve --port 4030
```

### Seed Built-in Presets (Optional, Idempotent)

```bash
python3 finops_agent.py seed-presets --db finops_audit.db
```

`serve` also seeds presets on startup if they are missing. The seeding is idempotent, so restarts do not grow the database; `GET /api/v1/presets/perfops-estate` is served from an in-memory cache and performs no writes.

## HTTP API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Service health check (`{"status": "ok", "service": "finops-cost-agent", "version": "1.1.0"}`) |
| `GET` | `/api/v1/catalog/skus` | Cloud, Hostinger KVM VPS, Docker cgroup, and LLM pricing catalog |
| `POST` | `/api/v1/analyze` | Analyze custom workloads, NAT egress, and LLM token budgets; returns USD & RUB annual savings |
| `GET` | `/api/v1/presets/perfops-estate` | Live FinOps audit of PerfOps & Globlex estate (`45.9.191.203`, Docker containers, cloud egress, AI routing) |
| `GET` | `/api/v1/audits` | List persisted FinOps audit runs from SQLite |

All endpoints except `GET /health` require `Authorization: Bearer <token>` when `FINOPS_API_TOKEN` is set. Without the variable the API stays public for backward compatibility and the service logs a warning at startup.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `FINOPS_DB_PATH` | `finops_audit.db` | SQLite database path (`:memory:` for ephemeral runs) |
| `FINOPS_API_TOKEN` | unset | Enables bearer-token auth for all non-health endpoints |
| `FINOPS_MAX_BODY_BYTES` | `1048576` (1 MiB) | Request body limit for regular endpoints |
| `FINOPS_MAX_BULK_BODY_BYTES` | `8388608` (8 MiB) | Request body limit for bulk endpoints (`POST /api/v1/analyze`) |
| `FINOPS_QUIET` | `0` | Set to `1` to silence access logs |

Requests over the limit are rejected with `413 payload_too_large` before the body is read.

## Testing

```bash
python3 -m unittest discover -s tests -v
```

## Contact / Support

PerfOps official Telegram contact: [@perfops_ai_manager](https://t.me/perfops_ai_manager).

For security vulnerabilities, use private vulnerability reporting rather than public Telegram messages.
