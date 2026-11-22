# API

Полная схема — OpenAPI на `/docs` (в режиме разработки, `APP_ENV=dev`). Все изменяющие запросы требуют заголовок `X-CSRF-Token` со значением cookie `pulse_csrf`.

| Группа | Эндпоинты | Роли |
|---|---|---|
| Вход | `POST /api/auth/register`, `/login`, `/logout`, `GET /api/auth/me` | все |
| Приглашения | `GET/POST /api/auth/invites`, `GET /api/auth/invites/{token}`, `POST …/accept` | HR; принятие — по ссылке |
| Программа | `GET/POST /api/programs`, `/api/participants`, `/api/pairs`, `POST /api/pairs/{id}/mentor`, `GET …/candidates`, `POST /api/pairs/{id}/outcome`, `GET /api/program/overview` | HR (чтение — HR, руководитель) |
| Загрузка | `POST /api/import/upload`, `GET/PUT /api/import/{job}/schema`, `POST /api/import/{job}/confirm` | HR |
| Дашборд | `GET /api/dashboard?period=&dept=`, `GET/PUT /api/dashboard/layout`, `POST /api/dashboard/tasks/{key}`, `GET /api/signals`, `POST /api/signals/{id}/verdict` | HR, руководитель |
| Карточка пары | `GET /api/pairs/{id}/diagnosis?topic=&scale=`, `POST /api/pairs/{id}/actions`, `POST /api/actions/{id}/status|agenda|outcomes`, `PUT /api/actions/{id}/outcomes`, `GET/POST /api/pairs/{id}/notes` | HR (чтение — руководитель) |
| LLM | `GET /api/llm/status`, `POST /api/pairs/{id}/explain|agenda|outcomes` | HR, руководитель |
| Формы | `GET /api/me`, `POST /api/responses`, `POST /api/me/talk`, `GET/POST /api/survey/{token}`, `GET /api/survey-links`, `POST /api/forms/yandex/webhook?token=`, `GET /api/forms/status|mailing`, `POST /api/forms/remind`, `PUT /api/forms/channels`, `POST /api/demo/test-response` | стороны / по ссылке / HR |
| Анкеты | `GET /api/questionnaires`, `POST /api/questions/suggest`, `POST /api/questions` | HR |
| События | `GET /api/events` (SSE: `pair_updated`, `data_imported`, `talk_request`), `GET /api/notifications`, `POST /api/notifications/read` | HR, руководитель / все |
| Настройки | `GET/PUT /api/settings`, `POST /api/settings/reset` | HR |
| Отчёт | `GET /api/reports?fmt=pdf|xlsx&period=all|last&parts=sum,pairs,signals,actions&dept=` | HR, руководитель |
| Обучение | `GET /api/learn`, `POST /api/courses`, `POST /api/courses/{id}/assign|progress`, `POST /api/tests/generate`, `PUT /api/tests/{id}/questions/{qid}`, `POST /api/tests/{id}/publish|answer` | по ролям |
| Ассистент | `POST /api/assistant` | все (ответ зависит от роли) |
| Служебное | `GET /health`, `GET /api/search` | все |
