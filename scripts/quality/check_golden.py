#!/usr/bin/env python
"""Валидатор golden dataset (DoD Q-01…Q-07).

Проверяет JSONL-набор против schemas/golden-example.json и дополнительные
инварианты, которые схемой не выражаются:

  Q-01  валидность по JSON Schema
  Q-02  объём набора
  Q-03  покрытие use cases (каждая UC >= 3 записей)
  Q-04  покрытие краевых случаев
  Q-05  баланс входов (фото/PDF >= 30% после разворота mixed_batch)
  Q-06  отсутствие PII (эвристика)
  Q-07  у каждой записи эталон, категория в глоссарии, notes при confidence < 0.9

Запуск:
    python scripts/quality/check_golden.py docs/quality/golden-dataset/v1.jsonl
    python scripts/quality/check_golden.py docs/quality/golden-dataset/v1.jsonl --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- Пороги (DoD §4). Меняются только вместе с dod.md. -----------------------
MIN_RECORDS = 30
MAX_RECORDS = 50
MIN_PER_UC = 3
MIN_INPUT_SHARE = 0.30
REQUIRED_EDGE_CASES = {
    "unreadable_photo",
    "pdf_no_text_layer",
    "mixed_receipt",
    "duplicate",
    "no_receipt",
}
CONFIDENCE_NOTES_THRESHOLD = 0.9

# --- PII-эвристики (Q-06). Намеренно консервативны: ложное срабатывание лучше
# пропуска, потому что набор уходит в публичный репозиторий. -------------------
PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "карта",
        # 13–19 цифр с разделителями — но НЕ внутри fiscal-реквизитов чека
        # (ФН/ФД/ФП — законные публичные идентификаторы, не персональные данные).
        # Проверка контекста вынесена в find_pii через _is_fiscal_path.
        re.compile(r"(?<![\d])(?:\d[ -]?){13,19}(?![\d])"),
    ),
    ("СНИЛС", re.compile(r"\b\d{3}-\d{3}-\d{3}[ -]?\d{2}\b")),
    ("паспорт", re.compile(r"\b\d{2}[ ]?\d{2}\s?№?\s?\d{6}\b")),
    ("ИНН 10/12", re.compile(r"\bИНН\s*\d{10,12}\b", re.IGNORECASE)),
    (
        "ФИО",
        # \s заменён на литеральный пробел: иначе шаблон склеивает конец одной
        # строки чека с началом следующей и даёт ложные срабатывания.
        re.compile(r"\b[А-ЯЁ][а-яё]+[ ][А-ЯЁ][а-яё]+[ ][А-ЯЁ][а-яё]+\b"),
    ),
    ("телефон", re.compile(r"(?:\+7|\b8)[\s(-]?\d{3}[\s)-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")),
]

# Пути, где 16-значные последовательности законны и не являются картой:
# фискальные реквизиты чека (ФН/ФД/ФП) из 54-ФЗ.
FISCAL_PATH_MARKERS = (".fiscal.", ".fiscal[")

# Явный белый список: синтетические реквизиты, разрешённые в наборе.
PII_ALLOWLIST = {
    "7701234567",
    "7712345678",
    "7734567890",
    "7704217370",
    "7756789012",
}


@dataclass
class Report:
    """Результат проверки: список (id, ok, detail)."""

    checks: list[tuple[str, bool, str]] = field(default_factory=list)

    def add(self, check_id: str, ok: bool, detail: str) -> None:
        self.checks.append((check_id, ok, detail))

    @property
    def ok(self) -> bool:
        return all(ok for _, ok, _ in self.checks)


def load_schema() -> dict[str, Any]:
    path = REPO_ROOT / "schemas" / "golden-example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Читает JSONL. Возвращает записи и список ошибок разбора."""
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    # utf-8-sig, а не utf-8: редакторы на Windows (и PowerShell Set-Content)
    # добавляют BOM, из-за которого первая строка JSONL перестаёт разбираться.
    for lineno, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"строка {lineno}: невалидный JSON: {exc.msg}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"строка {lineno}: ожидался объект, получено {type(obj).__name__}")
            continue
        records.append(obj)
    return records, errors


def validate_schema(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Q-01: валидация по JSON Schema.

    jsonschema желателен, но не обязателен: если его нет, проверяем встроенным
    валидатором, чтобы CI не падал на отсутствующей зависимости.
    """
    schema = load_schema()
    try:
        import jsonschema
    except ImportError:
        return _validate_schema_fallback(records, schema)

    validator = jsonschema.Draft202012Validator(schema)
    problems: list[str] = []
    for record in records:
        for err in validator.iter_errors(record):
            location = "/".join(str(p) for p in err.absolute_path) or "<root>"
            problems.append(f"{record.get('id', '?')}: {location}: {err.message}")
    if problems:
        head = "; ".join(problems[:5])
        more = f" (+{len(problems) - 5})" if len(problems) > 5 else ""
        return False, f"{len(problems)} ошибок схемы: {head}{more}"
    return True, f"{len(records)} записей валидны по схеме"


def _validate_schema_fallback(
    records: list[dict[str, Any]], schema: dict[str, Any]
) -> tuple[bool, str]:
    """Минимальная проверка обязательных полей и enum'ов без jsonschema."""
    required = set(schema["required"])
    input_schema = schema["properties"]["input"]
    input_required = set(input_schema["required"])
    ref_schema = schema["properties"]["reference"]
    ref_required = set(ref_schema["required"])
    meta_schema = schema["properties"]["meta"]
    meta_required = set(meta_schema["required"])
    type_enum = set(input_schema["properties"]["type"]["enum"])

    problems: list[str] = []
    for record in records:
        rid = record.get("id", "?")
        for key in required:
            if key not in record:
                problems.append(f"{rid}: нет обязательного поля {key}")
        inp = record.get("input", {})
        for key in input_required:
            if key not in inp:
                problems.append(f"{rid}: input.{key} обязателен")
        if inp.get("type") not in type_enum:
            problems.append(f"{rid}: input.type={inp.get('type')!r} вне enum")
        ref = record.get("reference", {})
        for key in ref_required:
            if key not in ref:
                problems.append(f"{rid}: reference.{key} обязателен")
        meta = record.get("meta", {})
        for key in meta_required:
            if key not in meta:
                problems.append(f"{rid}: meta.{key} обязателен")
    if problems:
        head = "; ".join(problems[:5])
        more = f" (+{len(problems) - 5})" if len(problems) > 5 else ""
        return False, f"{len(problems)} ошибок (встроенный валидатор): {head}{more}"
    return True, f"{len(records)} записей прошли встроенную проверку (jsonschema не установлен)"


def validate_volume(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Q-02: объём набора."""
    count = len(records)
    ok = MIN_RECORDS <= count <= MAX_RECORDS
    return ok, f"{count} записей (требуется {MIN_RECORDS}–{MAX_RECORDS})"


def validate_uc_coverage(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Q-03 / DoD P-04: каждая UC покрыта >= MIN_PER_UC записями."""
    per_uc: Counter[str] = Counter()
    for record in records:
        per_uc[str(record.get("meta", {}).get("uc_id", "?"))] += 1
    if not per_uc:
        return False, "ни одна запись не ссылается на UC"
    thin = {uc: n for uc, n in per_uc.items() if n < MIN_PER_UC}
    detail = ", ".join(f"{uc}={n}" for uc, n in sorted(per_uc.items()))
    if thin:
        bad = ", ".join(f"{uc}={n}" for uc, n in sorted(thin.items()))
        return False, f"UC с покрытием < {MIN_PER_UC}: {bad}; всего: {detail}"
    return True, f"{len(per_uc)} UC, минимум {min(per_uc.values())} записей; {detail}"


def validate_edge_cases(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Q-04: обязательные краевые случаи присутствуют."""
    present: Counter[str] = Counter()
    for record in records:
        edge = record.get("meta", {}).get("edge_case", "none")
        if edge and edge != "none":
            present[edge] += 1
    missing = sorted(REQUIRED_EDGE_CASES - set(present))
    detail = ", ".join(f"{k}={v}" for k, v in sorted(present.items())) or "нет"
    if missing:
        return False, f"нет краевых случаев: {', '.join(missing)}; есть: {detail}"
    return True, f"все {len(REQUIRED_EDGE_CASES)} обязательных; есть: {detail}"


def expand_inputs(records: list[dict[str, Any]]) -> list[str]:
    """Q-05: разворачивает mixed_batch в расходы по типу файла.

    Правило из golden-dataset-plan.md: каждый расход внутри пачки наследует тип
    своего файла. Если развернуть нельзя (нет позиций), запись считается один раз
    по своему типу и помечается как неизвестная для баланса.
    """
    expanded: list[str] = []
    for record in records:
        inp = record.get("input", {})
        kind = inp.get("type")
        if kind == "mixed_batch":
            items = inp.get("items") or []
            kinds = set()
            for item in items:
                name = str(item.get("name", "")).lower()
                if "фото" in name:
                    kinds.add("receipt_photo")
                elif "pdf" in name:
                    kinds.add("receipt_pdf")
            expanded.extend(sorted(kinds) if kinds else ["mixed_batch"])
        else:
            expanded.append(str(kind))
    return expanded


def validate_input_balance(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Q-05: доля каждого входа >= 30% после разворота."""
    kinds = expand_inputs(records)
    if not kinds:
        return False, "нет записей"
    counts = Counter(kinds)
    total = len(kinds)
    shares = {k: v / total for k, v in counts.items()}
    detail = ", ".join(f"{k}={v} ({shares[k]:.0%})" for k, v in sorted(counts.items()))
    bad = [k for k in ("receipt_photo", "receipt_pdf") if shares.get(k, 0.0) < MIN_INPUT_SHARE]
    if bad:
        return False, f"доля ниже {MIN_INPUT_SHARE:.0%}: {', '.join(bad)}; {detail}"
    return True, detail


def find_pii(records: list[dict[str, Any]]) -> list[str]:
    """Q-06: эвристический поиск PII во всех строковых значениях."""
    hits: list[str] = []

    def walk(rid: str, path: str, value: Any) -> None:
        if isinstance(value, str):
            if any(marker in path for marker in FISCAL_PATH_MARKERS):
                return
            for name, pattern in PII_PATTERNS:
                for match in pattern.finditer(value):
                    text = match.group(0)
                    if text in PII_ALLOWLIST:
                        continue
                    # ИНН-паттерн сам содержит слово ИНН — сравниваем только цифры.
                    digits = re.sub(r"\D", "", text)
                    if name == "ИНН 10/12" and digits in PII_ALLOWLIST:
                        continue
                    hits.append(f"{rid}: {path}: {name}: {text!r}")
        elif isinstance(value, dict):
            for key, sub in value.items():
                walk(rid, f"{path}.{key}", sub)
        elif isinstance(value, list):
            for idx, sub in enumerate(value):
                walk(rid, f"{path}[{idx}]", sub)

    for record in records:
        walk(str(record.get("id", "?")), "", record)
    return hits


def validate_no_pii(records: list[dict[str, Any]]) -> tuple[bool, str]:
    hits = find_pii(records)
    if hits:
        head = "; ".join(hits[:5])
        more = f" (+{len(hits) - 5})" if len(hits) > 5 else ""
        return False, f"{len(hits)} совпадений: {head}{more}"
    return True, "PII не найдены (эвристика)"


def load_glossary_categories() -> set[str] | None:
    """Категории политики. Источник — файл справочника, если он есть.

    Глоссарий содержит термины, а не категории, поэтому основной источник —
    docs/quality/golden-dataset/categories.txt (по строке на категорию).
    Если файла нет, проверка Q-07 по глоссарию пропускается с пометкой.
    """
    path = REPO_ROOT / "docs" / "quality" / "golden-dataset" / "categories.txt"
    if not path.exists():
        return None
    cats = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    return cats or None


def validate_reference(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Q-07: эталон заполнен, категория из справочника, notes при низкой уверенности."""
    categories = load_glossary_categories()
    problems: list[str] = []
    unknown: set[str] = set()

    for record in records:
        rid = str(record.get("id", "?"))
        ref = record.get("reference", {})
        if not ref.get("category"):
            problems.append(f"{rid}: пустая категория")
        if "reimbursable" not in ref:
            problems.append(f"{rid}: нет вердикта reimbursable")
        confidence = ref.get("confidence")
        if confidence is None:
            problems.append(f"{rid}: нет confidence")
        elif confidence < CONFIDENCE_NOTES_THRESHOLD and not ref.get("notes"):
            problems.append(f"{rid}: confidence={confidence} без notes")
        if categories and ref.get("category"):
            # Составная категория "A + B" проверяется по частям.
            for part in str(ref["category"]).split(" + "):
                if part not in categories:
                    unknown.add(part)

    if unknown:
        problems.append(f"категории вне справочника: {', '.join(sorted(unknown))}")
    if problems:
        head = "; ".join(problems[:5])
        more = f" (+{len(problems) - 5})" if len(problems) > 5 else ""
        source = (
            "справочник" if categories else "справочник не найден, проверка категорий пропущена"
        )
        return False, f"{len(problems)} проблем ({source}): {head}{more}"
    source = "категории сверены со справочником" if categories else "справочник не найден"
    return True, f"эталоны заполнены, {source}"


def validate_unique_ids(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Дополнительно: id уникальны (иначе SC-15 не посчитать)."""
    ids = [str(r.get("id", "?")) for r in records]
    dupes = [k for k, v in Counter(ids).items() if v > 1]
    if dupes:
        return False, f"дубли id: {', '.join(sorted(dupes))}"
    return True, f"{len(ids)} уникальных id"


def validate_rerun_integrity(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Дополнительно: run.rerun_of ссылается на существующий id (SC-15)."""
    ids = {str(r.get("id")) for r in records}
    dangling: list[str] = []
    reruns = 0
    for record in records:
        target = (record.get("run") or {}).get("rerun_of")
        if target:
            reruns += 1
            if str(target) not in ids:
                dangling.append(f"{record.get('id')} → {target}")
    if dangling:
        return False, f"битые ссылки rerun_of: {', '.join(dangling)}"
    return True, f"{reruns} записей-повторов, ссылки валидны"


# Номера болей PRD и их смысл. Нужны, чтобы поймать разметку, где номер боли
# не соответствует содержанию записи (docs/prd.md).
PRD_PAINS = {
    "pain_1_photo_quality": "фото чека не проходит из-за качества",
    "pain_2_pdf_format": "онлайн-чек приходит не в том формате",
    "pain_3_unclear_eligibility": "неясно заранее, подпадает ли покупка под компенсацию",
    "pain_4_missed_deadline": "дедлайн подачи легко пропустить",
    "pain_5_no_status_visibility": "нет видимости статуса заявки",
}


def validate_labels(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Дополнительно: pain_ref ссылается на реальную боль PRD, а сценарии —
    на известные scenario_ref. Ловит случай, когда номер боли приписан
    содержанию, к этой боли не относящемуся."""
    bad_pain: set[str] = set()
    pain_counts: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    for record in records:
        meta = record.get("meta", {})
        pain = meta.get("pain_ref")
        if pain:
            pain_counts[pain] += 1
            if pain not in PRD_PAINS:
                bad_pain.add(str(pain))
        scenario = meta.get("scenario_ref")
        if scenario:
            scenario_counts[scenario] += 1
    if bad_pain:
        return False, f"pain_ref вне списка болей PRD: {', '.join(sorted(bad_pain))}"
    pains = ", ".join(f"{k.split('_')[1]}={v}" for k, v in sorted(pain_counts.items()))
    scen = ", ".join(f"{k}={v}" for k, v in sorted(scenario_counts.items())) or "нет"
    return True, f"боли PRD: {pains}; сценарии: {scen}"


def validate_pain_coverage(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Дополнительно: покрыты ли боли PRD 1–3 (слой «чек -> категория -> вердикт»).

    Боли 4 (дедлайн) и 5 (статус) golden-набором не проверяются by design: это
    UX-слой, его меряют SC-09 и SC-21 в success-criteria.md. Проверка сообщает
    об этом явно, а не молчит, чтобы пробел в покрытии был виден.
    """
    covered: set[int] = set()
    for record in records:
        pain = record.get("meta", {}).get("pain_ref")
        if pain and pain.startswith("pain_"):
            try:
                covered.add(int(pain.split("_")[1]))
            except (IndexError, ValueError):
                continue
    expected = {1, 2, 3}
    missing = sorted(expected - covered)
    outside = sorted(covered - expected)
    detail = f"покрыты боли PRD {sorted(covered)}"
    if outside:
        detail += f" (вне зоны набора: {outside} — проверяются SC-09/SC-21)"
    if missing:
        return False, f"не покрыты боли PRD {missing}; {detail}"
    return True, detail


def build_report(path: Path) -> Report:
    report = Report()
    records, parse_errors = load_records(path)

    if parse_errors:
        report.add("parse", False, "; ".join(parse_errors[:5]))
    else:
        report.add("parse", True, f"{len(records)} строк прочитано")

    if not records:
        report.add("Q-01", False, "набор пуст")
        return report

    report.add("Q-01", *validate_schema(records))
    report.add("Q-02", *validate_volume(records))
    report.add("Q-03", *validate_uc_coverage(records))
    report.add("Q-04", *validate_edge_cases(records))
    report.add("Q-05", *validate_input_balance(records))
    report.add("Q-06", *validate_no_pii(records))
    report.add("Q-07", *validate_reference(records))
    report.add("Q-08", *validate_labels(records))
    report.add("pains", *validate_pain_coverage(records))
    report.add("ids", *validate_unique_ids(records))
    report.add("SC-15", *validate_rerun_integrity(records))
    return report


def print_report(path: Path, report: Report, as_json: bool) -> None:
    if as_json:
        payload = {
            "file": str(path.relative_to(REPO_ROOT))
            if path.is_relative_to(REPO_ROOT)
            else str(path),
            "ok": report.ok,
            "checks": [
                {"id": cid, "ok": ok, "detail": detail} for cid, ok, detail in report.checks
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"Golden dataset: {path}")
    print(f"{'ID':<8} {'РЕЗУЛЬТАТ':<10} ДЕТАЛИ")
    print("-" * 78)
    for check_id, ok, detail in report.checks:
        mark = "OK" if ok else "FAIL"
        print(f"{check_id:<8} {mark:<10} {detail}")
    print("-" * 78)
    print("ИТОГ:", "PASS" if report.ok else "FAIL")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Валидатор golden dataset (DoD Q-01…Q-07)")
    parser.add_argument("paths", nargs="+", type=Path, help="JSONL-файлы набора")
    parser.add_argument("--json", action="store_true", help="машинный отчёт")
    args = parser.parse_args(argv)

    overall_ok = True
    for path in args.paths:
        if not path.exists():
            print(f"Файл не найден: {path}", file=sys.stderr)
            overall_ok = False
            continue
        report = build_report(path)
        print_report(path, report, args.json)
        if not args.json:
            print()
        overall_ok = overall_ok and report.ok

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
