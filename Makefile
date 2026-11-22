.PHONY: up down logs model seed demo test lint fixtures validate dev admin

up:
	docker compose up -d --build
	$(MAKE) model
	@echo "Готово: http://localhost:8000"

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

dev:
	uv run alembic upgrade head && uv run uvicorn app.main:app --reload

test:
	uv run pytest -q

lint:
	uv run ruff check --fix . && uv run ruff format .

fixtures:
	uv run python -m ml.make_fixtures

validate:
	uv run python -m ml.validate

admin:
	uv run --group admin streamlit run admin/app.py
