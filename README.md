# ReleaseGuard

Платформа управления релизами с policy gates, ручным подтверждением,
canary-проверкой и автоматическим откатом. Проект моделирует критичную часть
delivery-процесса: артефакт нельзя подменить, параллельные релизы одного
окружения запрещены, CI-события подписаны и идемпотентны, а каждое решение
остаётся в аудите.

> English overview: a policy-driven release control plane built with FastAPI
> and PostgreSQL. It validates signed CI gates, serializes environment changes,
> evaluates canary SLOs, automatically rolls back unhealthy releases and ships
> with Prometheus, Grafana, Helm, Terraform and GitHub Actions.

## Статус проекта

Это самостоятельная портфолио-лаборатория для демонстрации DevOps-практик.
Конфигурации Kubernetes, Helm и Terraform являются воспроизводимым учебным
контуром, а не заявлением о коммерческой эксплуатации Kubernetes.

## Что реализовано

- неизменяемые артефакты по `sha256` digest и идемпотентное создание релиза;
- блокировка окружения через PostgreSQL `FOR UPDATE`;
- строгая машина состояний релиза;
- настраиваемые CI gates: tests, security и artifact signature;
- HMAC-SHA256 webhooks и дедупликация по `event_id`;
- обязательное ручное подтверждение для production;
- canary rollout с порогами error rate, p95 latency и minimum requests;
- автоматический и ручной rollback на предыдущую версию;
- reconciler с `SKIP LOCKED` для canary без метрик;
- append-only журнал решений и действий;
- Prometheus alerts и автоматически подключаемый Grafana dashboard;
- hardened non-root Docker image;
- Helm chart с probes, resources, HPA, PDB и NetworkPolicy;
- Terraform-модуль для namespace, secret и Helm release;
- GitHub Actions: quality gate, Helm/Terraform validation и OCI image с SBOM.

## Стек

Python 3.13, FastAPI, async SQLAlchemy, PostgreSQL 17, Alembic, Prometheus,
Grafana, Docker Compose, GitHub Actions, Helm, Kubernetes manifests, Terraform,
pytest, Ruff и mypy.

## Быстрый запуск

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
python scripts/smoke.py
```

Опциональная идемпотентная загрузка демонстрационного приложения:

```bash
docker compose exec api python -m releaseguard.seed
```

Сервисы:

- Swagger UI: <http://localhost:8091/docs>
- health check: <http://localhost:8091/health>
- Prometheus: <http://localhost:9099>
- Grafana: <http://localhost:3009> (`admin` / `releaseguard`)

Остановка:

```bash
docker compose down
```

## Quality gate

```bash
uv sync --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
docker compose config --quiet
helm lint deploy/helm/releaseguard
terraform -chdir=infra/terraform fmt -check
```

## Release flow

```text
evaluating -> blocked
evaluating -> awaiting_approval -> approved -> canary -> succeeded
                                              canary -> rolled_back
```

1. API резервирует окружение и создаёт релиз для immutable digest.
2. CI отправляет подписанные результаты обязательных gates.
3. Ответственный подтверждает production-релиз.
4. Релиз получает часть трафика.
5. Метрики приводят к promotion или rollback; отсутствие метрик — к timeout rollback.

Подробности находятся в [docs/architecture.md](docs/architecture.md), а
операционный сценарий — в [runbook](docs/runbooks/failed-canary.md). English
documentation is available in [README.en.md](README.en.md).

## Repository map

```text
src/releaseguard/       API, policy engine, state machine and reconciler
migrations/             PostgreSQL schema
observability/          Prometheus rules and Grafana provisioning
deploy/helm/            production-shaped Kubernetes package
infra/terraform/        namespace, secret and Helm release
docs/runbooks/          failure-response procedures
scripts/smoke.py        real release flow from CI gates to promotion
.github/workflows/      CI and immutable OCI publishing
```
