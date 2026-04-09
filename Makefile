.PHONY: install dev lint typecheck test

install:
	pnpm install
	python -m pip install -r requirements-dev.txt

dev:
	docker compose -f infra/docker/docker-compose.yml up --build

lint:
	pnpm -r lint
	ruff check apps packages

typecheck:
	pnpm -r typecheck
	mypy apps packages

test:
	pnpm -r test
	pytest
