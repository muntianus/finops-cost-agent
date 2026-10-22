# Security Policy

finops-cost-agent is an internal PerfOps microservice (default port 4030).

- **Report a vulnerability:** open a private security advisory on this repo
  (GitHub → Security → Advisories) or contact the owner listed in
  [`muntianus/.github`](https://github.com/muntianus/.github/blob/main/SECURITY.md).
- **Secrets:** `FINOPS_API_TOKEN` (optional bearer token) lives only in the deploy environment. Never commit `.env`; only
  `.env.example` (placeholder values) is tracked. GitGuardian scans every pull request for
  secrets.
- Set `FINOPS_API_TOKEN` in production: without it every endpoint is public (a startup warning says so). Request bodies are capped (1 MiB / 8 MiB bulk) and chunked uploads are refused.
