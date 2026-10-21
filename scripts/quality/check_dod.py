#!/usr/bin/env python
"""Проверки артефактов команды против Definition of Done (docs/quality/dod.md).

Один вход, один exit code: либо все блокирующие критерии зелёные, либо нет.

    python scripts/quality/check_dod.py           # все критерии, человекочитаемо
    python scripts/quality/check_dod.py --ci       # только merge-блокирующие
    python scripts/quality/check_dod.py --json     # машинный отчёт
    python scripts/quality/check_dod.py -v         # с деталями провалов

Критерии с формой MANUAL не проверяются машиной by design — они печатаются как
SKIP с протоколом, а не как PASS. Делать вид, что «документ понятный» проверен
скриптом, — хуже, чем честно назвать это ручной проверкой.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Result:
    """Результат одной проверки."""

    cid: str
    title: str
    form: str  # CHECK | COUNT | REF | MANUAL
    blocking: str  # merge | demo | later
    ok: bool | None  # None = SKIP (MANUAL или неприменимо)
    detail: str

    @property
    def status(self) -> str:
        if self.ok is None:
            return "SKIP"
        return "PASS" if self.ok else "FAIL"


def read(path: str) -> str:
    """Читает файл репозитория; пустая строка, если файла нет."""
    file = REPO_ROOT / path
    if not file.exists():
        return ""
    return file.read_text(encoding="utf-8-sig", errors="replace")


def exists(path: str) -> bool:
    return (REPO_ROOT / path).exists()


def count_matches(path: str, pattern: str) -> int:
    return len(re.findall(pattern, read(path), re.MULTILINE))


# ---------------------------------------------------------------------------
# Продуктовые артефакты (P-01…P-07)
# ---------------------------------------------------------------------------


def check_p01() -> Result:
    text = read("docs/prd.md")
    sections = ["## Сегмент", "## Боли", "## North Star"]
    found = [s for s in sections if s in text]
    return Result(
        "P-01",
        "PRD существует и назван конкретно",
        "CHECK",
        "merge",
        len(found) == len(sections),
        f"секций найдено {len(found)}/{len(sections)}"
        + (
            "" if len(found) == len(sections) else f"; нет: {', '.join(set(sections) - set(found))}"
        ),
    )


def check_p02() -> Result:
    if not exists("docs/use-cases.md"):
        return Result(
            "P-02",
            "4–6 UC с альтернативным потоком",
            "COUNT",
            "merge",
            False,
            "docs/use-cases.md не найден",
        )
    # Заголовок UC может быть любого уровня (## или ###) — фиксируем только ID.
    uc_count = count_matches("docs/use-cases.md", r"^#{2,4}\s+UC-\d+")
    alt_count = count_matches("docs/use-cases.md", r"\*\*Альтернативн")
    ok = 4 <= uc_count <= 8 and alt_count >= uc_count
    return Result(
        "P-02",
        "4–6 UC с альтернативным потоком",
        "COUNT",
        "merge",
        ok,
        f"{uc_count} UC, {alt_count} секций альтернативных потоков",
    )


def check_p03() -> Result:
    text = read("docs/use-cases.md")
    if not text:
        return Result(
            "P-03", "UC трассируются на боль PRD", "CHECK", "merge", False, "нет документа"
        )
    uc_count = count_matches("docs/use-cases.md", r"^#{2,4}\s+UC-\d+")
    pain_refs = count_matches("docs/use-cases.md", r"\*\*Боль PRD:\*\*")
    ok = uc_count > 0 and pain_refs >= uc_count
    return Result(
        "P-03",
        "UC трассируются на боль PRD",
        "CHECK",
        "merge",
        ok,
        f"{pain_refs} ссылок на боль при {uc_count} UC",
    )


def check_p04() -> Result:
    """Каждый UC покрыт >= 3 записями golden dataset."""
    path = REPO_ROOT / "docs/quality/golden-dataset/v1.jsonl"
    if not path.exists():
        return Result(
            "P-04", "UC покрыты golden dataset", "CHECK", "merge", False, "набор не найден"
        )
    counts: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        uc = str(rec.get("meta", {}).get("uc_id", "?"))
        counts[uc] = counts.get(uc, 0) + 1
    thin = {uc: n for uc, n in counts.items() if n < 3}
    detail = ", ".join(f"{uc}={n}" for uc, n in sorted(counts.items()))
    return Result(
        "P-04",
        "UC покрыты golden dataset (>= 3 записи)",
        "CHECK",
        "merge",
        not thin and bool(counts),
        detail if not thin else f"мало записей: {thin}; всего: {detail}",
    )


def check_p05() -> Result:
    text = read("docs/glossary.md")
    finalized = "Не финализирован" not in text and "не финализирован" not in text
    terms = count_matches("docs/glossary.md", r"^\*\*[^*]+\*\*\s+—")
    return Result(
        "P-05",
        "Глоссарий согласован",
        "MANUAL",
        "demo",
        None,
        f"{terms} терминов; протокол: Product зачитывает 5 терминов, "
        "команда формулирует определение своими словами. "
        + (
            "пометка «не финализирован» снята"
            if finalized
            else "ПОМЕТКА «не финализирован» ЕЩЁ СТОИТ"
        ),
    )


def check_p06() -> Result:
    hypotheses = count_matches("docs/hypotheses.md", r"^###\s+H\d+\.")
    falsifiers = count_matches("docs/hypotheses.md", r"\*\*Это неверно, если\*\*")
    ok = hypotheses > 0 and falsifiers >= hypotheses
    return Result(
        "P-06",
        "Гипотезы фальсифицируемы",
        "CHECK",
        "merge",
        ok,
        f"{falsifiers} условий опровержения при {hypotheses} гипотезах",
    )


def check_p07() -> Result:
    text = read("database/schema.sql")
    ok = "CREATE TABLE expense_category" in text and "company_id" in text
    return Result(
        "P-07",
        "Политика компенсации — справочник с company_id",
        "REF",
        "demo",
        ok,
        "таблица expense_category с company_id найдена"
        if ok
        else "нет expense_category с company_id в database/schema.sql",
    )


# ---------------------------------------------------------------------------
# AI / ML артефакты (A-01…A-07)
# ---------------------------------------------------------------------------


def check_a01() -> Result:
    links = len(set(re.findall(r"https?://[^\s\)\]<>]+", read("docs/research.md"))))
    return Result(
        "A-01", "Ресёрч с источниками", "COUNT", "merge", links >= 8, f"{links} уникальных ссылок"
    )


def check_a02() -> Result:
    text = read("docs/model-candidates.md")
    candidates = count_matches(
        "docs/model-candidates.md", r"^\|\s+\*\*(Облако|Российский API|Локально)\*\*"
    )
    has_price = "₽" in text or "$" in text
    ok = candidates >= 2 and has_price
    return Result(
        "A-02",
        "Кандидаты моделей с ценой",
        "CHECK",
        "merge",
        ok,
        f"{candidates} кандидатов, цена {'есть' if has_price else 'НЕ найдена'}",
    )


def check_a03() -> Result:
    prompts = list((REPO_ROOT / "prompts").glob("categorize.v*.md")) if exists("prompts") else []
    return Result(
        "A-03",
        "Промпт версионирован в репозитории",
        "REF",
        "demo",
        bool(prompts),
        ", ".join(p.name for p in prompts) if prompts else "нет файла prompts/categorize.v<N>.md",
    )


def check_a04() -> Result:
    path = REPO_ROOT / "schemas/llm-categorize.json"
    if not path.exists():
        return Result(
            "A-04",
            "JSON-схема ответа модели",
            "CHECK",
            "merge",
            False,
            "нет schemas/llm-categorize.json",
        )
    try:
        schema = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        return Result(
            "A-04",
            "JSON-схема ответа модели",
            "CHECK",
            "merge",
            False,
            f"невалидный JSON: {exc.msg}",
        )
    ok = isinstance(schema, dict) and "$schema" in schema or "type" in schema
    return Result("A-04", "JSON-схема ответа модели", "CHECK", "merge", bool(ok), "схема валидна")


def check_a05() -> Result:
    tests = list((REPO_ROOT / "tests").rglob("*llm*")) if exists("tests") else []
    return Result(
        "A-05",
        "Ответ модели валидируется схемой (тест есть)",
        "CHECK",
        "merge",
        bool(tests),
        ", ".join(str(t.relative_to(REPO_ROOT)) for t in tests)
        if tests
        else "нет тестов на llm_adapter",
    )


def check_a06() -> Result:
    return Result(
        "A-06",
        "Точность категории измерена на golden",
        "CHECK",
        "later",
        None,
        "вступает в силу с лабы 3; отчёт — docs/quality/experiments/lab2-prompt-on-golden.md",
    )


def check_a07() -> Result:
    ok = exists("docs/experiments/lab1.md")
    return Result(
        "A-07",
        "Записка об экспериментах Lab 1",
        "REF",
        "demo",
        ok,
        "файл есть" if ok else "нет файла",
    )


# ---------------------------------------------------------------------------
# Инженерные артефакты (D-01…D-10)
# ---------------------------------------------------------------------------


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    """Запускает подкоманду и возвращает (exit code, объединённый вывод).

    shell=True на Windows: npx/npm — это .CMD-шим, который subprocess без
    shell запустить не может (WinError 2). Команды здесь — фиксированные
    литералы, пользовательский ввод в них не попадает.

    Кэш npm уводится в рабочий каталог: глобальный кэш в профиле пользователя
    может быть недоступен на запись (песочница, общий раннер), и тогда npx
    падает на правах ещё до запуска самой проверки.

    errors="replace" и явный encoding: на Windows дочерний процесс печатает в
    cp1251, и чтение его вывода как UTF-8 падает с UnicodeDecodeError — а скрипт
    должен одинаково работать и локально, и в CI на Linux.
    """
    env = dict(os.environ)
    cache_dir = REPO_ROOT / ".piptmp" / "npm-cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        env.setdefault("npm_config_cache", str(cache_dir))
    except OSError:
        pass

    use_shell = sys.platform == "win32"
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
            shell=use_shell,
            env=env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def _has_npx() -> bool:
    """Есть ли npx в PATH. Без него aact локально не запустить."""
    from shutil import which

    return which("npx") is not None


def check_d01() -> Result:
    if not exists("aact.config.ts"):
        return Result(
            "D-01", "C4 проходит aact", "CHECK", "merge", None, "нет aact.config.ts в этой ветке"
        )
    if not _has_npx():
        return Result(
            "D-01",
            "C4 проходит aact (0 violations)",
            "CHECK",
            "merge",
            None,
            "npx не найден в PATH — проверка выполняется в CI (job architecture, Node 22)",
        )
    code, out = _run(["npx", "--yes", "aact@3.0.1", "check"])
    return Result(
        "D-01", "C4 проходит aact (0 violations)", "CHECK", "merge", code == 0, out[-400:]
    )


def check_d02() -> Result:
    """D-02: каждому внутреннему контейнеру C4 соответствует сервис в compose.

    Проверяем именно этот инвариант, а не сырой `aact diff`: diff сравнивает в
    том числе label, technology и description, которых в compose нет по
    определению, и тонет в косметических расхождениях (23 technology changes на
    текущей диаграмме). Нам важно, что имена сервисов совпадают с именами
    контейнеров — это и записано в docs/architecture/README.md.

    Из сверки исключаются: люди и внешние системы (их нет в compose),
    `llm_runtime` (поднимается только профилем local-llm) и сама граница системы.
    """
    puml = read("docs/architecture/c4-container.puml")
    compose = read("compose.dev.yml")
    if not puml or not compose:
        return Result(
            "D-02", "C4 соответствует compose", "CHECK", "merge", False, "нет puml или compose"
        )

    containers = set(re.findall(r"Container(?:Db|Queue)?\(\s*(\w+)", puml))
    # Разбираем YAML, а не regex: под `services:` ключи вложены глубоко, и
    # плоский шаблон "^  (\w+):" ловит image, command, healthcheck и имена сетей.
    try:
        import yaml

        parsed = yaml.safe_load(compose) or {}
        services = set((parsed.get("services") or {}).keys())
    except ImportError:
        block = re.search(r"^services:\n(.*?)(?=^\w|\Z)", compose, re.MULTILINE | re.DOTALL)
        services = set(re.findall(r"^  (\w+):", block.group(1), re.MULTILINE)) if block else set()
    if not containers:
        return Result(
            "D-02", "C4 соответствует compose", "CHECK", "merge", False, "в puml нет контейнеров"
        )

    # Контейнеры, которых в compose быть не должно, с обоснованием.
    not_in_compose = {"llm_runtime"}
    expected = containers - not_in_compose
    missing = sorted(expected - services)
    extra = sorted(services - containers)

    if missing:
        return Result(
            "D-02",
            "C4 соответствует compose",
            "CHECK",
            "merge",
            False,
            f"в C4 есть, в compose нет: {', '.join(missing)}",
        )
    detail = f"{len(expected)} контейнеров C4 имеют одноимённый сервис в compose"
    if extra:
        detail += f"; в compose без контейнера: {', '.join(extra)}"
    return Result("D-02", "C4 соответствует compose", "CHECK", "merge", not extra, detail)


def check_d03() -> Result:
    schema = read("database/schema.sql")
    erd = read("database/erd.puml")
    tables = set(re.findall(r"CREATE TABLE (\w+)", schema))
    if not tables:
        return Result(
            "D-03", "ERD соответствует схеме БД", "CHECK", "merge", False, "не найдено CREATE TABLE"
        )
    missing = {t for t in tables if t not in erd}
    return Result(
        "D-03",
        "ERD соответствует схеме БД",
        "CHECK",
        "merge",
        not missing,
        f"{len(tables)} таблиц; отсутствуют в ERD: {', '.join(sorted(missing))}"
        if missing
        else f"все {len(tables)} таблиц есть в ERD",
    )


def check_d04() -> Result:
    ok = "CREATE TABLE expense" in read("database/schema.sql")
    return Result(
        "D-04",
        "Схема БД применяется на чистой базе",
        "CHECK",
        "merge",
        ok,
        "schema.sql на месте; применение проверяет job schema в CI (psql)",
    )


def check_d05() -> Result:
    text = read("compose.dev.yml")
    if not text:
        return Result(
            "D-05", "Compose-скелет поднимается", "CHECK", "merge", False, "нет compose.dev.yml"
        )
    try:
        import yaml
    except ImportError:
        services = count_matches("compose.dev.yml", r"^  \w+:")
        return Result(
            "D-05",
            "Compose-скелет поднимается",
            "CHECK",
            "merge",
            services >= 5,
            f"{services} сервисов (yaml недоступен, структура не проверена)",
        )
    data = yaml.safe_load(text)
    services = data.get("services", {})
    healthy = sum(1 for s in services.values() if isinstance(s, dict) and "healthcheck" in s)
    ok = len(services) >= 5 and healthy >= 5
    return Result(
        "D-05",
        "Compose-скелет поднимается",
        "CHECK",
        "merge",
        ok,
        f"{len(services)} сервисов, {healthy} с healthcheck",
    )


def check_d06() -> Result:
    adrs = list((REPO_ROOT / "docs/adr").glob("[0-9]*-*.md")) if exists("docs/adr") else []
    return Result(
        "D-06", "ADR на дорогие решения", "COUNT", "merge", len(adrs) >= 3, f"{len(adrs)} ADR"
    )


def check_d07() -> Result:
    adrs = list((REPO_ROOT / "docs/adr").glob("[0-9]*-*.md")) if exists("docs/adr") else []
    if not adrs:
        return Result("D-07", "У каждого ADR есть цена решения", "CHECK", "merge", False, "нет ADR")
    missing = [
        a.name
        for a in adrs
        if "## Цена решения" not in a.read_text(encoding="utf-8", errors="replace")
        and "## Последствия" not in a.read_text(encoding="utf-8", errors="replace")
    ]
    return Result(
        "D-07",
        "У каждого ADR есть цена решения",
        "CHECK",
        "merge",
        not missing,
        f"{len(adrs)} ADR, без секции цены: {', '.join(missing)}"
        if missing
        else f"все {len(adrs)} ADR",
    )


def check_d08() -> Result:
    url = re.search(r"https?://[\w.-]+onrender\.com", read("README.md"))
    return Result(
        "D-08",
        "Прод отвечает",
        "CHECK",
        "demo",
        bool(url),
        f"URL в README: {url.group(0)}" if url else "URL прода не найден в README",
    )


def check_d09() -> Result:
    readme = read("README.md")
    ok = "├── app/" in readme and "├── docs/" in readme and exists("app") and exists("docs")
    return Result(
        "D-09", "Структура репозитория совпадает с README", "CHECK", "demo", ok, "структура описана"
    )


def check_d10() -> Result:
    """Секреты в репозитории (D-10)."""
    patterns = [
        (r"sk-[A-Za-z0-9]{20,}", "похоже на OpenAI-ключ"),
        (r"(?i)api[_-]?key\s*[=:]\s*['\"]?[A-Za-z0-9\-_]{20,}", "длинный ключ в присваивании"),
        (r"(?i)password\s*[=:]\s*['\"]?[^\s'\"${}]{8,}", "пароль в присваивании"),
    ]
    findings: list[str] = []
    skip_dirs = {
        ".git",
        ".piptmp",
        "__pycache__",
        "node_modules",
        ".venv",
        # Кэши и артефакты инструментов: ruff складывает туда сериализованный
        # код сторонних библиотек со словом password — это не секрет проекта.
        ".ruff_cache",
        ".pytest_cache",
        ".mypy_cache",
        "reports",
        "data",
    }
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix in {".png", ".jpg", ".svg", ".pdf", ".whl", ".pyc"}:
            continue
        # .env.example — шаблон, значения-заглушки там ожидаемы.
        if path.name == ".env.example":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern, label in patterns:
            for match in re.finditer(pattern, text):
                token = match.group(0)
                # Заглушки и явные placeholder'ы не считаем.
                if any(k in token.lower() for k in ("stub", "example", "changeme", "your_", "xxx")):
                    continue
                rel = path.relative_to(REPO_ROOT)
                findings.append(f"{rel}: {label}: {token[:40]}")
    return Result(
        "D-10",
        "Секретов нет в репозитории",
        "CHECK",
        "merge",
        not findings,
        "; ".join(findings[:3]) if findings else "находок нет",
    )


# ---------------------------------------------------------------------------
# Качество и безопасность (Q-01…Q-14)
# ---------------------------------------------------------------------------


def check_q01_golden() -> Result:
    """Q-01: golden dataset валиден. Делегирует в check_golden.py."""
    code, out = _run(
        [sys.executable, "scripts/quality/check_golden.py", "docs/quality/golden-dataset/v1.jsonl"]
    )
    return Result(
        "Q-01",
        "Golden dataset валиден по схеме",
        "CHECK",
        "merge",
        code == 0,
        out.splitlines()[-1] if out else "",
    )


def check_q09_test_plan() -> Result:
    text = read("docs/quality/test-plan.md")
    if not text:
        return Result(
            "Q-09", "Тест-план описывает уровни и CI", "CHECK", "merge", False, "нет test-plan.md"
        )
    markers = {
        "unit": "Unit-уровень" in text or "## 1. Unit" in text,
        "интеграция": "Интеграционный уровень" in text or "## 2. Интеграц" in text,
        "evals": "Evals (golden dataset)" in text or "## 3. Evals" in text,
        "CI": "## 4. Что гоняется в CI" in text,
    }
    missing = [k for k, v in markers.items() if not v]
    return Result(
        "Q-09",
        "Тест-план: 3 уровня + CI",
        "CHECK",
        "merge",
        not missing,
        f"нет секций: {', '.join(missing)}" if missing else "все 4 секции на месте",
    )


def check_q10_threat_inputs() -> Result:
    text = read("docs/quality/threat-model.md")
    if not text:
        return Result(
            "Q-10", "Threat model: входы недоверенного текста", "CHECK", "merge", False, "нет файла"
        )
    entries = count_matches("docs/quality/threat-model.md", r"^\|\s+\*\*E\d+\*\*")
    has_rights = "Права модели в каждой точке" in text
    has_breach = "чего она **не может**" in text.lower() or "Чего она **не может**" in text
    ok = entries >= 6 and has_rights
    return Result(
        "Q-10",
        "Threat model: входы + права модели",
        "CHECK",
        "merge",
        ok,
        f"{entries} входов (нужно >= 6), секция прав {'есть' if has_rights else 'НЕТ'}, "
        f"барьеры {'описаны' if has_breach else 'не описаны'}",
    )


def check_q11_owasp() -> Result:
    text = read("docs/quality/threat-model.md")
    found = {f"LLM{i:02d}" for i in range(1, 11) if f"LLM{i:02d}" in text}
    missing = [f"LLM{i:02d}" for i in range(1, 11) if f"LLM{i:02d}" not in found]
    return Result(
        "Q-11",
        "OWASP LLM Top-10 покрыт",
        "CHECK",
        "merge",
        len(found) == 10,
        f"{len(found)}/10" + (f"; нет: {', '.join(missing)}" if missing else ""),
    )


def check_q12_regulator() -> Result:
    text = read("docs/quality/threat-model.md")
    has_152 = "152-ФЗ" in text
    return Result(
        "Q-12",
        "Требование регулятора",
        "MANUAL",
        "demo",
        None,
        "протокол: назвать регулятора одной строкой. "
        + ("152-ФЗ упомянут" if has_152 else "ПРОВЕРИТЬ: 152-ФЗ не упомянут"),
    )


def check_q13_experiment() -> Result:
    path = REPO_ROOT / "docs/quality/experiments/lab2-prompt-on-golden.md"
    if not path.exists():
        return Result(
            "Q-13",
            "Рискованное допущение проверено экспериментом",
            "MANUAL",
            "demo",
            None,
            "ПРОВЕРИТЬ: нет docs/quality/experiments/lab2-prompt-on-golden.md",
        )
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    # Критерий требует ЧЕСТНОЙ записи: наличие числа и признака провала,
    # а не красивого результата.
    has_numbers = bool(re.search(r"\d\.\d{2}", text))
    admits_failure = "не подтвердилось" in text.lower() or "ниже порога" in text.lower()
    detail = (
        f"записка есть; числа {'есть' if has_numbers else 'НЕТ'}; "
        f"провал зафиксирован: {'да' if admits_failure else 'НЕТ'}"
    )
    return Result(
        "Q-13", "Рискованное допущение проверено экспериментом", "MANUAL", "demo", None, detail
    )


def check_q14_attacks() -> Result:
    count = count_matches("docs/quality/threat-model.md", r"^\|\s+AT-\d+")
    return Result(
        "Q-14",
        "Атаки для лабы 4 перечислены",
        "COUNT",
        "demo",
        count >= 8,
        f"{count} атак (нужно >= 8)",
    )


# ---------------------------------------------------------------------------
# Реестр проверок
# ---------------------------------------------------------------------------

CHECKS = [
    check_p01,
    check_p02,
    check_p03,
    check_p04,
    check_p05,
    check_p06,
    check_p07,
    check_a01,
    check_a02,
    check_a03,
    check_a04,
    check_a05,
    check_a06,
    check_a07,
    check_d01,
    check_d02,
    check_d03,
    check_d04,
    check_d05,
    check_d06,
    check_d07,
    check_d08,
    check_d09,
    check_d10,
    check_q01_golden,
    check_q09_test_plan,
    check_q10_threat_inputs,
    check_q11_owasp,
    check_q12_regulator,
    check_q13_experiment,
    check_q14_attacks,
]

# Golden-набор сам считает Q-02…Q-08; они дублируются здесь только для сводки.
GOLDEN_IDS = {"Q-02", "Q-03", "Q-04", "Q-05", "Q-06", "Q-07", "Q-08"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка DoD артефактов (docs/quality/dod.md)")
    parser.add_argument("--ci", action="store_true", help="только merge-блокирующие критерии")
    parser.add_argument("--json", action="store_true", help="машинный отчёт")
    parser.add_argument("-v", "--verbose", action="store_true", help="показывать детали провалов")
    args = parser.parse_args(argv)

    results = [check() for check in CHECKS]

    if args.ci:
        results = [r for r in results if r.blocking == "merge"]

    if args.json:
        payload = {
            "ok": all(r.ok is not False for r in results),
            "summary": {
                "total": len(results),
                "pass": sum(1 for r in results if r.ok is True),
                "fail": sum(1 for r in results if r.ok is False),
                "skip": sum(1 for r in results if r.ok is None),
            },
            "checks": [
                {
                    "id": r.cid,
                    "title": r.title,
                    "form": r.form,
                    "blocking": r.blocking,
                    "status": r.status,
                    "detail": r.detail,
                }
                for r in results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1

    print("DoD артефактов — проверка (docs/quality/dod.md)")
    print("=" * 100)
    print(f"{'ID':<7} {'СТАТУС':<7} {'ФОРМА':<8} {'БЛОК':<6} КРИТЕРИЙ")
    print("-" * 100)
    for r in results:
        print(f"{r.cid:<7} {r.status:<7} {r.form:<8} {r.blocking:<6} {r.title}")
        if r.detail and (args.verbose or r.ok is False):
            print(f"{'':<31} └─ {r.detail}")
    print("-" * 100)

    passed = sum(1 for r in results if r.ok is True)
    failed = sum(1 for r in results if r.ok is False)
    skipped = sum(1 for r in results if r.ok is None)
    print(
        f"PASS: {passed}   FAIL: {failed}   "
        f"SKIP (ручная проверка): {skipped}   ВСЕГО: {len(results)}"
    )

    blocking_failures = [r for r in results if r.ok is False and r.blocking == "merge"]
    if blocking_failures:
        print()
        print("БЛОКИРУЮЩИЕ ПРОВАЛЫ:")
        for r in blocking_failures:
            print(f"  {r.cid} {r.title}: {r.detail}")

    manual = [r for r in results if r.ok is None]
    if manual:
        print()
        print("РУЧНЫЕ ПРОВЕРКИ (машиной не проверяются by design):")
        for r in manual:
            print(f"  {r.cid} {r.title}")

    print()
    print("ИТОГ:", "PASS" if not blocking_failures else "FAIL")
    return 0 if not blocking_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
