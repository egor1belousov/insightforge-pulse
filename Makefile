.PHONY: up up-gpu down logs model seed demo demo-fast test lint fixtures template validate dev admin \
	prod-up prod-down prod-logs prod-warm prod-demo deploy

up:
	docker compose up -d --build
	$(MAKE) model
	@echo "Готово: http://localhost:8000"

up-gpu:
	docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
	$(MAKE) model
	@echo "Готово (Ollama на GPU): http://localhost:8000"

down:
	docker compose down

logs:
	docker compose logs -f app

model:
	docker compose exec -T ollama ollama pull $${OLLAMA_MODEL:-qwen2.5:3b-instruct}

seed:
	docker compose exec -T app python -m app.seed

demo:
	docker compose exec -T app python -m app.seed --reset

demo-fast:
	docker compose exec -T app python -m app.seed --reset --fast

dev:
	uv run alembic upgrade head && uv run uvicorn app.main:app --reload

test:
	uv run pytest -q

lint:
	uv run ruff check --fix . && uv run ruff format .

fixtures:
	uv run python -m ml.make_fixtures

template:
	uv run python -m ml.make_template

validate:
	uv run python -m ml.validate

admin:
	uv run --group admin streamlit run admin/app.py

# ---------- сервер (см. docs/DEPLOY.md) ----------
PROD = docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f docker-compose.prod.yml
PROD_DIR ?= /opt/pulse

prod-up:
	$(PROD) up -d --build --remove-orphans
	m=$$(grep -s ^OLLAMA_MODEL= .env | cut -d= -f2); $(PROD) exec -T ollama ollama pull $${m:-qwen2.5:3b-instruct}
	$(MAKE) prod-warm
	@if ! $(PROD) exec -T db psql -U pulse -tAc "select 1 from users limit 1" 2>/dev/null | grep -q 1; then $(MAKE) prod-demo; fi
	@echo "Готово: https://$$(grep ^DOMAIN= .env | cut -d= -f2)"

prod-down:
	$(PROD) down

prod-logs:
	$(PROD) logs -f --tail=200 app caddy

prod-warm:
	$(PROD) exec -T app python -m app.services.llm.warm

prod-demo:
	$(PROD) exec -T app python -m app.seed --reset

deploy:
	@test -n "$(HOST)" || (echo "Укажите сервер: make deploy HOST=root@1.2.3.4" && exit 1)
	rsync -az --delete --exclude-from=deploy/rsync-exclude ./ $(HOST):$(PROD_DIR)/
	ssh $(HOST) 'cd $(PROD_DIR) && make prod-up'
