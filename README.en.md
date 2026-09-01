# ReleaseGuard

ReleaseGuard is an executable DevOps portfolio lab for policy-driven delivery.
It accepts signed CI gate results, serializes deployments per environment,
requires optional human approval, evaluates canary SLOs and rolls unhealthy or
timed-out releases back to their previous version.

The Kubernetes, Helm and Terraform assets demonstrate learned practices; they
do not claim commercial Kubernetes operations experience.

## Highlights

- immutable SHA-256 artifacts and idempotent release requests;
- PostgreSQL environment locking and an explicit release state machine;
- HMAC-authenticated, deduplicated CI webhooks;
- configurable quality/security/signature gates;
- canary thresholds and timeout reconciliation with `SKIP LOCKED`;
- append-only audit journal and manual/automatic rollback;
- Prometheus alerts, provisioned Grafana dashboard and operational runbook;
- non-root container, Helm probes/HPA/PDB/NetworkPolicy and Terraform wiring;
- GitHub Actions validation and OCI publishing with provenance and SBOM.

## Run locally

```bash
cp .env.example .env
docker compose up --build -d
python scripts/smoke.py
```

Open the API at <http://localhost:8091/docs>, Prometheus at
<http://localhost:9099>, and Grafana at <http://localhost:3009>.

