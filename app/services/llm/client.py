"""Клиент локальной Ollama: строгий JSON по Pydantic-схеме, temperature=0, повтор, таймаут."""

import json
import logging
import time
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.settings import get_settings

log = logging.getLogger("pulse.llm")
T = TypeVar("T", bound=BaseModel)
PROMPTS = Path(__file__).parent / "prompts"

_status: dict = {"ok": None, "checked": 0.0, "latency": None, "error": None, "info": {}}
_stats: dict = {"calls": 0, "cached": 0, "failed": 0, "seconds": 0.0}
# temperature=0: одинаковый запрос даёт одинаковый ответ, поэтому повтор отдаём из памяти
_cache: dict[tuple[str, str, str, str], BaseModel] = {}


def prompt(name: str, **values: str) -> str:
    """Текст промпта из prompts/{name}.md с подстановкой значений."""
    text = (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def enabled() -> bool:
    """Включена ли LLM в настройках и отвечала ли она недавно."""
    s = get_settings()
    if not s.llm_enabled:
        return False
    return not (_status["ok"] is False and time.monotonic() - _status["checked"] < 30)


def chat_json[T: BaseModel](
    system: str, user: str, schema: type[T], *, timeout: float | None = None, retries: int = 1
) -> T | None:
    """Запрос к модели с ответом строго по схеме.

    Returns:
        Объект схемы или None, если модель недоступна или дважды вернула невалидный JSON.
    """
    if not enabled():
        return None
    s = get_settings()
    key = (s.ollama_model, schema.__name__, system, user)
    if key in _cache:
        _stats["cached"] += 1
        return _cache[key].model_copy(deep=True)
    body = {
        "model": s.ollama_model,
        "stream": False,
        "format": schema.model_json_schema(),
        "options": {"temperature": 0, "num_ctx": 4096, "num_predict": s.llm_max_tokens},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    for attempt in range(retries + 1):
        t0 = time.monotonic()
        try:
            r = httpx.post(f"{s.ollama_url}/api/chat", json=body, timeout=timeout or s.ollama_timeout)
            r.raise_for_status()
            content = r.json()["message"]["content"]
            _stats["calls"] += 1
            _stats["seconds"] += time.monotonic() - t0
            _status.update(
                ok=True, checked=time.monotonic(), latency=round(time.monotonic() - t0, 2), error=None
            )
            result = schema.model_validate(json.loads(content))
            if len(_cache) >= s.llm_cache_size:
                _cache.pop(next(iter(_cache)))
            _cache[key] = result
            return result.model_copy(deep=True)
        except (httpx.HTTPError, KeyError) as e:
            _stats["failed"] += 1
            _status.update(ok=False, checked=time.monotonic(), error=str(e)[:200])
            log.warning("Ollama недоступна: %s", e)
            return None
        except (json.JSONDecodeError, ValidationError) as e:
            log.warning("Невалидный ответ модели (попытка %s): %s", attempt + 1, e)
            body["messages"].append(
                {"role": "user", "content": "Ответ не соответствует схеме. Верни только JSON по схеме."}
            )
    return None


def _model_info(s, names: list[dict]) -> dict:
    """Сведения о модели из Ollama: размер, квантизация, загружена ли в видеопамять."""
    m = next((x for x in names if x["name"].startswith(s.ollama_model)), None)
    if m is None:
        return {}
    d = m.get("details", {})
    info = {
        "name": m["name"],
        "params": d.get("parameter_size"),
        "quant": d.get("quantization_level"),
        "family": d.get("family"),
        "size_gb": round(m.get("size", 0) / 1e9, 1),
        "loaded": False,
        "vram_gb": None,
        "version": None,
    }
    try:
        ps = httpx.get(f"{s.ollama_url}/api/ps", timeout=3).json().get("models", [])
        run = next((x for x in ps if x["name"].startswith(s.ollama_model)), None)
        if run:
            info.update(loaded=True, vram_gb=round(run.get("size_vram", 0) / 1e9, 1))
        info["version"] = httpx.get(f"{s.ollama_url}/api/version", timeout=3).json().get("version")
    except (httpx.HTTPError, ValueError):
        pass
    return info


def status(check: bool = False) -> dict:
    """Состояние LLM для экрана настроек: живые данные из Ollama и счётчики запросов."""
    s = get_settings()
    if check and s.llm_enabled:
        t0 = time.monotonic()
        try:
            r = httpx.get(f"{s.ollama_url}/api/tags", timeout=5)
            r.raise_for_status()
            models = r.json().get("models", [])
            ok = any(m["name"].startswith(s.ollama_model) for m in models)
            _status.update(
                ok=ok,
                checked=time.monotonic(),
                latency=round(time.monotonic() - t0, 2),
                error=None if ok else f"Модель {s.ollama_model} не скачана: make model",
                info=_model_info(s, models),
            )
        except httpx.HTTPError as e:
            _status.update(ok=False, checked=time.monotonic(), error=str(e)[:200], info={})
    calls = _stats["calls"]
    return {
        "enabled": s.llm_enabled,
        "model": s.ollama_model,
        "url": s.ollama_url,
        "ok": _status["ok"],
        "latency": _status["latency"],
        "error": _status["error"],
        "info": _status["info"],
        "stats": {
            "calls": calls,
            "cached": _stats["cached"],
            "failed": _stats["failed"],
            "avg_seconds": round(_stats["seconds"] / calls, 1) if calls else None,
        },
    }
