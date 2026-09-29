.PHONY: sync format lint type test integration check up down smoke seed helm terraform

sync:
	uv sync --frozen --extra dev

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

type:
	uv run mypy src

test:
	uv run pytest

integration:
	docker compose --profile test build test
	docker compose --profile test run --rm test

check: lint type test integration
	docker compose config --quiet

up:
	docker compose up --build -d

down:
	docker compose down

smoke:
	python scripts/smoke.py

seed:
	docker compose exec api python -m releaseguard.seed

helm:
	helm lint deploy/helm/releaseguard
	helm template test deploy/helm/releaseguard >/tmp/releaseguard-rendered.yaml

terraform:
	terraform -chdir=infra/terraform fmt -check
