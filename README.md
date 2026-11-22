# Пульс адаптации

Сервис для HR: показывает, где оценки стажёра и наставника расходятся во времени, объясняет причину и подсказывает действие. Решение всегда принимает HR.

Команда InsightForge, кейс-чемпионат «Код города» (МГТС), направление «ИИ и автоматизация процессов».

## Быстрый запуск

Нужны Docker и Docker Compose.

```bash
cp .env.example .env      # при необходимости поменяйте SECRET_KEY и DEMO_PASSWORD
make up                   # поднимает db, app, ollama и скачивает модель qwen2.5:3b-instruct
make demo                 # чистая база + демо-данные и демо-аккаунты
```

Приложение: http://localhost:8000, проверка: http://localhost:8000/health.

Демо-аккаунты (пароль — `DEMO_PASSWORD` из `.env`): `hr@pulse.demo`, `lead@pulse.demo`, `mentor@pulse.demo`, `intern@pulse.demo`.

Ollama по умолчанию работает на процессоре. С видеокартой NVIDIA и установленным `nvidia-container-toolkit`:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

Если Ollama недоступна, приложение продолжает работать на запасных правилах.

## Локальная разработка

```bash
uv sync
uv run alembic upgrade head      # по умолчанию SQLite ./pulse.db
uv run python -m app.seed --reset
uv run uvicorn app.main:app --reload
```

Проверки перед PR:

```bash
uv run ruff check --fix && uv run ruff format && uv run pytest -q
```

## Документация

- `docs/SPEC.md` — спецификация.
- `docs/ARCHITECTURE.md`, `docs/METHODOLOGY.md`, `docs/FORMS.md`, `docs/DEMO.md` — архитектура, методика, коннекторы форм, сценарий защиты.
- `docs/STATUS.md` — состояние этапов.
