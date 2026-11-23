"""Прогрев модели: загрузка в видеопамять навсегда и пробный запрос со схемой JSON.

Первый запрос после загрузки идёт заметно дольше обычного, поэтому делаем его заранее.
Запуск: python -m app.services.llm.warm
"""

import time

import httpx

from app.core.settings import get_settings
from app.services.llm import client
from app.services.llm.tasks import TextAnswer


def main() -> None:
    """Загружает модель с keep_alive=-1 и проверяет время ответа."""
    s = get_settings()
    t0 = time.monotonic()
    r = httpx.post(
        f"{s.ollama_url}/api/generate", json={"model": s.ollama_model, "keep_alive": -1}, timeout=300
    )
    r.raise_for_status()
    print(f"Модель {s.ollama_model} загружена в видеопамять за {time.monotonic() - t0:.1f} с")
    for i in range(2):
        t0 = time.monotonic()
        res = client.chat_json(
            "Отвечай кратко.", f"Пробный запрос {i}: скажи «готово».", TextAnswer, timeout=120
        )
        state = "ответ получен" if res else "нет ответа"
        print(f"Пробный запрос {i + 1}: {state} за {time.monotonic() - t0:.1f} с")


if __name__ == "__main__":
    main()
