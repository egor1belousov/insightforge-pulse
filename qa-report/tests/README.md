# Автотесты mgtspulse.ru (Playwright, TypeScript)

## Установка (один раз)
```bash
cd qa-report/tests
npm install
npx playwright install chromium firefox
# WebKit (Safari) — нужны системные библиотеки:
# sudo npx playwright install-deps webkit && npx playwright install webkit
```

## Запуск
```bash
npx playwright test                         # все тесты на всех проектах (~15 мин)
npx playwright test --project=chromium-1440 # только десктоп Chromium
npx playwright test specs/functional.spec.ts
QA_BASE=http://localhost:8000 npx playwright test   # другой стенд
npx playwright show-report ../playwright-report     # HTML-отчёт
./lighthouse.sh https://mgtspulse.ru                 # Lighthouse mobile/desktop → ../lighthouse/
```

## Проекты
| Проект | Что гоняется |
|---|---|
| `chromium-1440` | всё, кроме сугубо мобильных сценариев |
| `chromium-768`, `firefox-1440`, `firefox-375` | вёрстка `@ui`: скриншоты страниц, скролл вбок, консоль, изображения |
| `chromium-375` (iPhone SE) | вёрстка `@ui` и мобильные сценарии `@mobile` (панель вкладок, модалки, тач) |

## Наборы
| Файл | ID из тест-плана |
|---|---|
| `specs/functional.spec.ts` | F01–F14 |
| `specs/forms-auth.spec.ts` | N01–N06, A01–A07 |
| `specs/states-nav.spec.ts` | S01–S05, V01–V04 |
| `specs/ui.spec.ts` | U01–U03 |
| `specs/a11y.spec.ts` | X01–X03 (axe-core, клавиатура, подписи) |
| `specs/security-seo.spec.ts` | B01–B07, P02–P03 |

## Тестовые данные
Все создаваемые данные — с префиксом `qa_test_`: компании и HR (`qa_test_hr_…@example.com`),
приглашённые (`qa_test_mentor_…`, `qa_test_intern_…`), потоки, материалы, заметки. Почта
`@example.com` — несуществующая, письма никуда не уходят. Демо-входы создают песочницы, они
удаляются сами через 6 часов.
