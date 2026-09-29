# ReleaseGuard

Сервис учёта и проверки решений о выпуске релизов. Он принимает подписанные результаты CI, требует отдельного утверждения, оценивает канареечные метрики и фиксирует откат в PostgreSQL. Это портфолио-лаборатория: поле `traffic_percent` и статус отката описывают решение, но сами по себе не меняют маршрутизацию трафика или развёртывание. Для этого нужен отдельный исполнитель команд в инфраструктуре.

## Возможности

- Неизменяемый идентификатор артефакта `sha256:`, повторяемое создание релиза по ключу и блокировка окружения в PostgreSQL.
- Роли клиентов: администратор создаёт и запускает релизы, утверждающий подтверждает их, источник метрик отправляет наблюдения, читатель просматривает историю. Имя участника аудита определяется ключом, а не телом запроса.
- Результаты CI подписаны HMAC-SHA256 и дедуплицируются по `event_id`. Результат уже зафиксированной проверки нельзя незаметно заменить.
- Канареечная проверка сопоставляет число запросов, долю ошибок и p95 с порогами окружения. Отдельный процесс переводит зависшие релизы в состояние отката.
- Журнал событий, метрики Prometheus, панель Grafana, миграции Alembic, Compose и проверки GitHub Actions.

Архитектура, модель конкуренции и границы работы описаны в [технической документации](docs/architecture.md). Для разбора неудачной проверки есть [операционная памятка](docs/runbooks/failed-canary.md).

## Запуск

```bash
cp .env.example .env
docker compose up --build -d
python scripts/smoke.py
```

API: <http://localhost:8091/docs>; Prometheus: <http://localhost:9099>; Grafana: <http://localhost:3009>. Порты привязаны к `127.0.0.1`. Демонстрационные ключи и пароль Grafana указаны в `.env.example`; перед использованием вне локальной машины их необходимо заменить.

В `API_CLIENTS` задаётся JSON-объект: имя клиента → `{"key":"...", "role":"admin|approver|observer|viewer"}`. Ключи должны быть уникальными и содержать не менее 16 символов. API-запросы, кроме проверок состояния и метрик, требуют `Authorization: Bearer <ключ>`. CI-уведомления используют отдельный `WEBHOOK_SECRET` и заголовок `X-ReleaseGuard-Signature: sha256=<HMAC тела>`. Роль утверждающего отделена от роли администратора.

Основные маршруты:

| Метод | Путь | Роль |
|---|---|---|
| `POST` | `/api/v1/applications` | Администратор |
| `POST` | `/api/v1/applications/{id}/environments` | Администратор |
| `POST` | `/api/v1/environments/{id}/releases` | Администратор |
| `POST` | `/api/v1/webhooks/ci` | Подпись CI |
| `POST` | `/api/v1/releases/{id}/approve` | Утверждающий |
| `POST` | `/api/v1/releases/{id}/deploy` | Администратор |
| `POST` | `/api/v1/releases/{id}/observations` | Источник метрик |
| `POST` | `/api/v1/releases/{id}/rollback` | Администратор |
| `GET` | `/api/v1/releases/{id}`, `/events` | Любой известный клиент |

Скрипт `scripts/smoke.py` использует локальные демонстрационные ключи. Для другой конфигурации задайте `RELEASEGUARD_ADMIN_KEY`, `RELEASEGUARD_APPROVER_KEY`, `RELEASEGUARD_OBSERVER_KEY` и `RELEASEGUARD_WEBHOOK_SECRET`.

## Проверки

```bash
uv sync --frozen --extra dev
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
docker compose config --quiet
docker compose --profile test build test
docker compose --profile test run --rm test
helm lint deploy/helm/releaseguard
terraform -chdir=infra/terraform fmt -check
```

Локальный `pytest` пропускает интеграционные тесты без выделенной базы `releaseguard_test`. Контейнерная проверка применяет миграции в отдельной базе и проверяет роли, конкурентное создание, откаты и reconciler. CI также проверяет Helm, Terraform и сборку образа. Настоящее применение Terraform требует внешнего кластера и настройки секретов; оно здесь не заявляется проверенным.

Остановка без удаления данных: `docker compose down`.
