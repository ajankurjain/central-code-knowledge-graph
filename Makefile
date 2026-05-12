.PHONY: help up down logs restart build ps psql neo4j-shell redis-cli api-shell worker-shell test lint check install-hooks clean

help:
	@echo "central-code-knowledge-graph — make targets"
	@echo "  up            Start the full stack (Neo4j + Postgres + Redis + API + worker)"
	@echo "  down          Stop and remove containers"
	@echo "  logs          Tail logs from all services"
	@echo "  restart       Restart the API and worker"
	@echo "  build         Rebuild service images"
	@echo "  ps            List running services"
	@echo "  psql          Open a psql shell inside the Postgres container"
	@echo "  neo4j-shell   Open a cypher-shell inside the Neo4j container"
	@echo "  redis-cli     Open redis-cli inside the Redis container"
	@echo "  api-shell     Open a bash shell inside the API container"
	@echo "  worker-shell  Open a bash shell inside the worker container"
	@echo "  test          Run the test suite (pytest, in the api container)"
	@echo "  lint          Run ruff against ckg + tests (in the api container)"
	@echo "  check         lint + test — the exact gate CI runs"
	@echo "  install-hooks Install the git pre-push hook that runs 'make check'"
	@echo "  clean         Remove volumes (WARNING: deletes all graph data)"

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

restart:
	docker compose restart api worker

build:
	docker compose build

ps:
	docker compose ps

psql:
	docker compose exec postgres psql -U $${POSTGRES_USER:-ckg} -d $${POSTGRES_DB:-ckg}

neo4j-shell:
	docker compose exec neo4j cypher-shell -u $${NEO4J_USER:-neo4j} -p $${NEO4J_PASSWORD:-change-me-neo4j-password}

redis-cli:
	docker compose exec redis redis-cli

api-shell:
	docker compose exec api bash

worker-shell:
	docker compose exec worker bash

web-shell:
	docker compose exec web sh

web-dev:
	cd web && npm install --legacy-peer-deps && npm run dev

test:
	@docker compose exec -T api bash -lc 'cd /app && pip install -q pytest pytest-asyncio >/dev/null 2>&1 && pytest -q --ignore=tests/integration'

# Mirrors `.github/workflows/ci.yml` — ruff against ckg + tests. Runs
# inside the api container so we use the same Python the image ships
# with and don't depend on the contributor's host toolchain.
lint:
	@docker compose exec -T api bash -lc 'cd /app && (command -v ruff >/dev/null || pip install -q ruff) && ruff check ckg tests'

# The exact gate CI runs. Use this as your pre-push check.
check: lint test

install-hooks:
	@./scripts/install-git-hooks.sh

clean:
	docker compose down -v
