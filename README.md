# RDDH — Учёт расходов по чекам и выпискам

[![CI](https://github.com/vstu-sii/rddh-5jwf/actions/workflows/ci.yml/badge.svg)](https://github.com/vstu-sii/rddh-5jwf/actions/workflows/ci.yml)

Проект курса «Системы искусственного интеллекта» (ВолгГТУ, магистратура).

## О проекте

Бухгалтер небольшой компании или человек с общим бюджетом вручную разносит чеки и банковские выписки по категориям расходов. Чек приходит фотографией, выписка — таблицей, а категория часто не следует напрямую из названия продавца. Часть разноски — жёсткие правила, часть — привычки конкретного человека.

Проект помогает автоматически категоризировать операции по российским чекам и выпискам так, чтобы месяц сходился с фактом, а разбирать руками нужно было только по-настоящему спорные случаи.

Подробности — в [`docs/prd.md`](docs/prd.md) (сегмент, боли, North Star) и [`docs/glossary.md`](docs/glossary.md) (глоссарий команды).

## Прод

**URL:** https://rddh-hello-world.onrender.com

Сейчас в проде — заглушка (`GET /`, `GET /health`), задеплоенная на Render.com. Прод существует с первой недели и дальше только наращивается.

## Структура репозитория

```
.
├── app/                     # Backend API (FastAPI) — контейнер `api`
├── stubs/                   # HTTP-заглушка для ещё не реализованных сервисов C4
├── frontend/prototype/      # Кликабельный прототип UI + скриншоты
├── database/
│   ├── schema.sql           # Схема PostgreSQL (baseline)
│   ├── erd.puml             # ERD
│   └── migrations/          # Правила миграций
├── tests/                   # Тесты
├── scripts/quality/         # Проверки DoD, валидатор golden dataset, раннер evals
├── schemas/                 # JSON-схемы: golden-запись и ответ LLM
├── prompts/                 # Версионированные промпты (categorize.v1.md)
├── docs/
│   ├── architecture/        # C4 (context, container) в PlantUML + отрендеренные SVG
│   ├── adr/                 # Архитектурные решения с ценой решения
│   ├── quality/             # DoD, golden dataset, тест-план, модель угроз
│   └── ...                  # PRD, use cases, ресёрч, модели, эксперименты, деплой
├── .github/
│   ├── workflows/ci.yml     # CI: lint, format, test, aact, schema, build, compose
│   └── PULL_REQUEST_TEMPLATE.md
├── aact.config.ts           # Правила проверки архитектуры (aact)
├── compose.dev.yml          # Dev-скелет: все контейнеры C4 (заглушки + Postgres, Redis, S3)
├── .env.example             # Переменные окружения (шаблон)
├── Dockerfile
├── render.yaml              # Blueprint для деплоя на Render.com
├── requirements.txt         # Зависимости приложения
└── requirements-dev.txt     # + зависимости для разработки (lint, тесты)
```

Архитектура и как её проверять — [docs/architecture/README.md](docs/architecture/README.md).

Структуру дополняем по мере роста проекта — решает команда.

## Как поднять локально

Требуется Docker и Docker Compose.

```bash
cp .env.example .env
docker compose -f compose.dev.yml up --build
```

Поднимаются все контейнеры из C4: настоящие Postgres (`expense_db`, схема применяется автоматически), Redis (`task_queue`), S3-хранилище SeaweedFS (`receipt_files`), API и HTTP-заглушки ещё не реализованных сервисов — каждый с healthcheck. Порты настраиваются в `.env`.

| Что | Адрес |
| --- | --- |
| Backend API | http://localhost:8000/health |
| Приложение сотрудника (прототип) | http://localhost:3000/employee.html |
| Кабинет бухгалтера (прототип) | http://localhost:3001/backoffice.html |
| БД | `docker compose -f compose.dev.yml exec expense_db psql -U rddh` |

Подъём занимает меньше 10 минут на чистой машине с уже установленным Docker (повторный — меньше минуты). Локальная LLM (Ollama, ~5 ГБ) по умолчанию не поднимается: `docker compose -f compose.dev.yml --profile local-llm up`.

Сети повторяют архитектуру: к БД и файлам подключён только `expense_store`, в интернет выходят только ACL-адаптеры.

### Без Docker (локальный Python)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

### Тесты и линтер

```bash
pytest
ruff check .
ruff format --check .
```

## Качество и безопасность

Артефакты роли Quality & Safety: [DoD команды](docs/quality/dod.md), [golden dataset](docs/quality/golden-dataset/README.md), [тест-план](docs/quality/test-plan.md), [модель угроз](docs/quality/threat-model.md).

Все проверки запускаются одной командой и возвращают exit code (0 — можно мёржить):

```bash
pip install jsonschema pyyaml   # нужны для полной валидации

python scripts/quality/check_dod.py            # все критерии DoD
python scripts/quality/check_dod.py --ci      # только блокирующие мёрж
python scripts/quality/check_golden.py docs/quality/golden-dataset/v1.jsonl
python scripts/quality/run_evals.py --dataset docs/quality/golden-dataset/v1.jsonl --provider baseline
```

Первые три гоняются в CI на каждый PR (джобы `quality` и `evals-smoke`), поэтому «зелёный CI» означает в том числе, что golden dataset валиден и критерии DoD выполнены.

## Ветвление и Pull Request

- Ветка на задачу: `lab<N>-<role>-<short-topic>`, например `lab1-delivery-initiation`.
- `main` — защищённая ветка: мёрж только через PR, CI обязателен и должен быть зелёным.
- Заголовок PR для лабораторных: `Lab<N>: <Role> — <Deliverable>`.
- Шаблон PR подтягивается автоматически из [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md).
- Секреты живут только в `.env` (не коммитится); в репозитории — только `.env.example`.

## Команда

| Роль | Отвечает за |
|---|---|
| Product / VO | Сегмент, боли, гипотезы, глоссарий, общий язык |
| AI Engineer | Ресёрч, кандидаты моделей, эксперименты, ADR |
| Delivery | Репозиторий, окружение, CI, прод |
| Quality & Safety | Критерии успеха, метрики, golden dataset, DoD |

Состав команды и контакты — во внутренней документации курса.

## CI

Workflow `.github/workflows/ci.yml` гоняется на каждый PR и пуш в `main`:

| Job | Что проверяет |
| --- | --- |
| `lint-and-test` | `ruff check`, `ruff format --check`, `pytest` |
| `architecture` | `aact check` по C4 Container — 0 нарушений |
| `schema` | `database/schema.sql` накатывается на чистый PostgreSQL 16 |
| `build` | Сборка Docker-образа API |
| `compose` | Dev-скелет поднимается, все healthcheck зелёные, smoke-запросы к API и фронтендам |

Мёрж в `main` заблокирован, пока CI не зелёный.
