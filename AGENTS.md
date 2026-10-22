# AGENTS.md — finops-cost-agent

Org-wide rules: [`muntianus/.github/AGENT_POLICY.md`](https://github.com/muntianus/.github/blob/main/AGENT_POLICY.md)
and the [Repository Standard](https://github.com/muntianus/.github/blob/main/docs/standards/REPOSITORY_STANDARD.md).

## Repo-local rules

- **Zero dependencies.** Python ≥ 3.11 standard library only (`http.server`, `sqlite3`, `unittest`); adding a package needs an ADR.
- **Contract first.** A route change updates `ROUTES` in `finops_service/server.py` and
  `docs/api/openapi.json` in the same commit; `tests/test_openapi_contract.py` fails on drift.
- **Config is env-only.** Every variable the code reads is listed in `.env.example`;
  never commit `.env`.
- **`GET /health` stays dependency-free** (liveness only).
- **Auth is checked before routing.** Every route except `GET /health` goes through `_is_authorized` (constant-time compare); unknown paths answer 401 before 404 so the surface is not enumerable without a token.
- **GET endpoints never write SQLite.** Presets are served from the startup cache; only `POST /api/v1/analyze` (with `persist`) and the one-time seed write.
- Before pushing: `python3 -m unittest discover -s tests -v`.
- Conventional commits; branch `feat/*` / `fix/*` / `chore/*`; never push to `main`.
