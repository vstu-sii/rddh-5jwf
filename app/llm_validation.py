"""Проверка ответа LLM перед записью в расход (DoD A-05, threat-model §4).

Модуль реализует шаги 1–5 из `prompts/categorize.v1.md` §4: ответ модели
принимается только после проверки схемой и справочником компании. Всё, что
не прошло, помечается degraded — молчаливой записи произвольного ответа нет.

Здесь же живёт асимметрия `needs_review`: приложение может выставить флаг,
но не может снять его по просьбе модели.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "llm-categorize.json"

# Порог из PRD (черновой, пересматривается с Quality по фактам прогонов).
CONFIDENCE_THRESHOLD = 0.85

# Маркеры попытки управлять моделью из текста документа (LLM01).
# Список намеренно широкий: ложное срабатывание стоит одной ручной проверки,
# пропуск — неверной выплаты.
INJECTION_MARKERS = (
    "игнорируй",
    "игнорировать",
    "ignore previous",
    "ignore all",
    "system override",
    "system:",
    "система]",
    "[система",
    "ассистенту",
    "assistant:",
    "как ассистент",
    "выставь",
    "установи category",
    "reimbursable=true",
    "needs_review=false",
    "не помечай",
    "do not report",
    "new instructions",
    "override",
)


@dataclass
class Decision:
    """Результат обработки ответа модели."""

    accepted: bool
    degraded: bool
    category: str | None
    confidence: float | None
    needs_review: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "degraded": self.degraded,
            "category": self.category,
            "confidence": self.confidence,
            "needs_review": self.needs_review,
            "reasons": self.reasons,
        }


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8-sig"))


def _validate_by_schema(payload: Any) -> list[str]:
    """Валидация ответа по JSON Schema. Возвращает список проблем."""
    schema = _load_schema()
    try:
        import jsonschema
    except ImportError:
        return _validate_by_schema_fallback(payload, schema)
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in validator.iter_errors(payload)
    ]


def _validate_by_schema_fallback(payload: Any, schema: dict[str, Any]) -> list[str]:
    """Проверка обязательных полей и типов без jsonschema."""
    problems: list[str] = []
    if not isinstance(payload, dict):
        return [f"ожидался объект, получено {type(payload).__name__}"]
    for key in schema["required"]:
        if key not in payload:
            problems.append(f"{key}: обязательное поле отсутствует")
    if "confidence" in payload:
        value = payload["confidence"]
        if not isinstance(value, int | float) or isinstance(value, bool):
            problems.append("confidence: ожидалось число")
        elif not 0 <= value <= 1:
            problems.append("confidence: вне диапазона 0..1")
    if "needs_review" in payload and not isinstance(payload["needs_review"], bool):
        problems.append("needs_review: ожидался boolean")
    for key in ("category", "merchant_canonical"):
        if key in payload and (not isinstance(payload[key], str) or not payload[key].strip()):
            problems.append(f"{key}: ожидалась непустая строка")
    return problems


def detect_injection(*texts: str | None) -> bool:
    """Ищет в текстах документа маркеры попытки управлять моделью (LLM01)."""
    for text in texts:
        if not text:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in INJECTION_MARKERS):
            return True
    return False


def process_llm_response(
    raw_response: str | None,
    *,
    allowed_categories: set[str] | None = None,
    document_texts: tuple[str | None, ...] = (),
    app_needs_review: bool = False,
) -> Decision:
    """Обрабатывает сырой ответ модели и решает, можно ли его принять.

    Шаги:
      1. JSON разбирается            — нет  -> degraded
      2. Проходит схему              — нет  -> degraded
      3. Категория в справочнике     — нет  -> needs_review, категория отброшена
      4. confidence < порога         — да   -> needs_review
      5. В документе есть инъекция   — да   -> needs_review
    """
    reasons: list[str] = []
    needs_review = bool(app_needs_review)
    if app_needs_review:
        reasons.append("проверка назначена приложением")

    # Шаг 1: JSON.
    if not raw_response or not raw_response.strip():
        return Decision(False, True, None, None, True, ["пустой ответ модели"])
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return Decision(False, True, None, None, True, [f"ответ не является JSON: {exc.msg}"])

    # Шаг 2: схема.
    problems = _validate_by_schema(payload)
    if problems:
        return Decision(
            False,
            True,
            None,
            None,
            True,
            [f"ответ не прошёл схему ({len(problems)})", *problems[:3]],
        )

    category = str(payload["category"]).strip()
    confidence = float(payload["confidence"])

    # Шаг 3: категория из справочника компании (SC-14).
    if allowed_categories is not None and category not in allowed_categories:
        return Decision(
            False,
            False,
            None,
            confidence,
            True,
            [*reasons, f"категория вне справочника компании: {category!r}"],
        )

    # Шаг 4: порог уверенности.
    if confidence < CONFIDENCE_THRESHOLD:
        needs_review = True
        reasons.append(f"уверенность {confidence} ниже порога {CONFIDENCE_THRESHOLD}")

    # Шаг 5: инъекция в тексте документа.
    if detect_injection(*document_texts):
        needs_review = True
        reasons.append("в тексте документа найдена попытка управлять системой")

    # Асимметрия: модель может только ПРОСИТЬ проверку, не снимать её.
    if payload["needs_review"]:
        needs_review = True
        reasons.append("модель запросила ручную проверку")

    return Decision(True, False, category, confidence, needs_review, reasons)
