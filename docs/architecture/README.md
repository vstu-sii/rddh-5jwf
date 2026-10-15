# Архитектура RDDH

Архитектура описана as-code в PlantUML и проверяется машиной (aact). Исходник `.puml` — источник истины; SVG в `rendered/` — для просмотра, перегенерируются из исходника.

| Артефакт | Исходник | Картинка |
| --- | --- | --- |
| C4 Level 1 — System Context | [c4-context.puml](c4-context.puml) | [rendered/c4-context.svg](rendered/c4-context.svg) |
| C4 Level 2 — Container | [c4-container.puml](c4-container.puml) | [rendered/c4-container.svg](rendered/c4-container.svg) |
| ERD | [../../database/erd.puml](../../database/erd.puml) | [rendered/erd.svg](rendered/erd.svg) |
| Решения об архитектуре | [../adr/](../adr/) | — |

## Что зафиксировано

Сотрудник загружает фото или PDF чека в PWA → `api` сохраняет файл через `expense_store` и ставит задачу в очередь → `recognition_worker` прогоняет QR/текст PDF/OCR, нормализует продавца и предлагает категорию через `llm_adapter` → результат и метрики прогона сохраняются → сотрудник подтверждает поля → спорные расходы попадают бухгалтеру в кабинет → бухгалтер решает с обязательной причиной и формирует реестр.

Актёры MVP — **сотрудник** и **бухгалтер** (гипотеза команды). HR-администратор политики и руководитель-согласующий в MVP не моделируются: политика категорий заводится как справочник, согласование делает бухгалтер. Если Product добавит их в роадмап, понадобится ревизия контейнеров: каждый новый актёр меняет устойчивость фронтендов в расчёте aact `stableDependencies`.

Ключевые решения: [ADR-0001](../adr/0001-async-recognition-pipeline.md) — асинхронный конвейер через очередь; [ADR-0002](../adr/0002-single-data-owner.md) — единственный владелец данных; [ADR-0003](../adr/0003-acl-adapters-for-external-systems.md) — внешние системы только через ACL-адаптеры.

## Проверка aact

Конфиг — [aact.config.ts](../../aact.config.ts) в корне, источник — `c4-container.puml`. Нужен Node.js ≥ 22.

```bash
npx --yes aact@3.0.1 check     # 0 violations — иначе CI красный
npx --yes aact@3.0.1 analyze   # метрики связности
```

| Правило | Статус | Что гарантирует в нашей системе |
| --- | --- | --- |
| `acl` | вкл. | Во внешние системы ходят только `llm_adapter` и `fns_adapter` (тег `acl`) |
| `acyclic` | вкл. | Нет циклов зависимостей между контейнерами |
| `crud` | вкл. | В БД и файловое хранилище ходит только `expense_store` (тег `repo`), а он — только в хранилища |
| `dbPerService` | вкл. | У каждого хранилища ровно один владелец |
| `cohesion` | вкл. | Граница системы связнее внутри, чем снаружи |
| `stableDependencies` | вкл. | Зависимости направлены к более стабильным контейнерам |
| `commonReuse` | вкл. | Потребители используют публичную поверхность контекста целиком |
| `apiGateway` | **выкл.** | Общего egress-шлюза в MVP нет — обоснование и цена в ADR-0003 |

Почему 0 нарушений не случайность: правила проверены на испорченной копии диаграммы — прямой `api → expense_db` и `recognition_worker → cloud_llm` дают 5 нарушений по 4 правилам и exit code 1.

Контекстная диаграмма в aact не подаётся: на уровне L1 система сама обращается к внешним системам, и правило `acl` на этом уровне неприменимо.

### Соответствие C4 и compose

Имена сервисов в `compose.dev.yml` совпадают с именами контейнеров. Сверка:

```bash
npx --yes aact@3.0.1 diff docs/architecture/c4-container.puml compose.dev.yml --current-format compose
```

Ожидаемые и единственные расхождения: люди, внешние системы и граница системы (их нет в compose), связь `llm_adapter → llm_runtime` (Ollama поднимается только с профилем `local-llm`, поэтому без `depends_on`).

## Как перерисовать картинки

Нужны Java и Graphviz, `plantuml.jar` — с [plantuml.com](https://plantuml.com/download).

```bash
java -jar plantuml.jar -charset UTF-8 -tsvg -o rendered docs/architecture/c4-context.puml docs/architecture/c4-container.puml
java -jar plantuml.jar -charset UTF-8 -tsvg -o ../docs/architecture/rendered database/erd.puml
```

Библиотека C4 подключается из стандартной поставки PlantUML (`!include <C4/...>`), интернет при рендере не нужен.
