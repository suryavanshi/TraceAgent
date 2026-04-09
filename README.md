# TraceAgent Monorepo (AI PCB Design Agent)

This repository is the initial scaffold for an AI-assisted PCB design platform. It uses a monorepo layout so web, API, worker, and shared domain packages can evolve together.

## Architecture overview

- **apps/web**: Next.js + TypeScript frontend.
- **apps/api**: FastAPI service exposing API endpoints.
- **apps/worker**: Python worker for asynchronous tasks.
- **packages/schemas**: shared JSON Schema and Python Pydantic models.
- **packages/design-ir**: canonical design IR types + diff helpers.
- **packages/llm**: provider abstraction and model interfaces.
- **packages/kicad**: KiCad execution helpers.
- **packages/verification**: ERC/DRC/report normalization.
- **packages/ui-shared**: shared TypeScript UI types/helpers.
- **infra/docker**: local containerized development stack.

## Repo layout

```txt
apps/
  web/
  api/
  worker/
packages/
  schemas/
  design-ir/
  llm/
  kicad/
  verification/
  ui-shared/
infra/
  docker/
```

## Tooling

- **Node.js 20+**
- **pnpm 9+** (workspace management for JS/TS packages)
- **Python 3.12**
- **Docker + Docker Compose**

## Quick start (local, non-Docker)

1. Copy environment templates:
   ```bash
   cp .env.example .env
   cp apps/api/.env.example apps/api/.env
   cp apps/worker/.env.example apps/worker/.env
   cp apps/web/.env.example apps/web/.env.local
   ```
2. Install dependencies:
   ```bash
   make install
   ```
3. Run all services in dev mode:
   ```bash
   make dev
   ```

## Docker-based local development

```bash
docker compose -f infra/docker/docker-compose.yml up --build
```

Services:
- Web: http://localhost:3000
- API: http://localhost:8000
- API health: http://localhost:8000/health
- Postgres: localhost:5432
- Redis: localhost:6379

## Common commands

```bash
make install
make dev
make lint
make typecheck
make test
```

## CI

GitHub Actions workflow (`.github/workflows/ci.yml`) runs lint and tests for both JS and Python components.
