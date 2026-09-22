# RDDH — Учёт расходов по чекам и выпискам

[![CI](https://github.com/vstu-sii/rddh-5jwf/actions/workflows/ci.yml/badge.svg)](https://github.com/vstu-sii/rddh-5jwf/actions/workflows/ci.yml)

Проект курса «Системы искусственного интеллекта» (ВолгГТУ, магистратура).

## О проекте

Бухгалтер небольшой компании или человек с общим бюджетом вручную разносит чеки и банковские выписки по категориям расходов. Чек приходит фотографией, выписка — таблицей, а категория часто не следует напрямую из названия продавца. Часть разноски — жёсткие правила, часть — привычки конкретного человека.

Проект помогает автоматически категоризировать операции по российским чекам и выпискам так, чтобы месяц сходился с фактом, а разбирать руками нужно было только по-настоящему спорные случаи.

Подробности — в [`docs/prd.md`](docs/prd.md) (сегмент, боли, North Star) и [`docs/glossary.md`](docs/glossary.md) (глоссарий команды).

## Прод

**URL:** TODO — будет вписан после первого деплоя, см. [`docs/deploy.md`](docs/deploy.md)

Сейчас в проде — заглушка (`GET /`, `GET /health`), задеплоенная на Render.com. Прод существует с первой недели и дальше только наращивается.

## Структура репозитория

```
.
├── app/                     # Код приложения (FastAPI)
│   └── main.py
├── tests/                   # Тесты
├── docs/                    # Документация команды (PRD, ресёрч, quality, деплой...)
├── .github/
│   ├── workflows/ci.yml     # CI: lint, format, test, build
│   └── PULL_REQUEST_TEMPLATE.md
├── compose.dev.yml          # Dev-окружение (приложение + БД)
├── .env.example             # Переменные окружения (шаблон)
├── Dockerfile
├── render.yaml              # Blueprint для деплоя на Render.com
├── requirements.txt         # Зависимости приложения
└── requirements-dev.txt     # + зависимости для разработки (lint, тесты)
```

Структуру дополняем по мере роста проекта — решает команда.

## Как поднять локально

Требуется Docker и Docker Compose.

```bash
cp .env.example .env
docker compose -f compose.dev.yml up --build
```

Приложение поднимется на `http://localhost:8000` (порт настраивается через `APP_PORT` в `.env`). Проверить:

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

Подъём занимает меньше 10 минут на чистой машине с уже установленным Docker.

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

Workflow `.github/workflows/ci.yml` гоняется на каждый PR и пуш в `main`: `ruff check`, `ruff format --check`, `pytest`, сборка Docker-образа. Мёрж в `main` заблокирован, пока CI не зелёный.
