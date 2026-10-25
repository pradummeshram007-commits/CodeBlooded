"""The short worst-case writeup.

The LLM gets only the computed summary (top items, not the contracts) and writes 150-250
words of plain English in date order, citing contract and clause ids. It must not compute or
invent anything: code checks that every number and date in its text exists in the computed
data. One retry with the offending tokens named; then a template writeup. If the LLM is
down or over budget, the template is used and says so. Never raises.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

from odin.llm import BudgetExceeded, LLMError
from odin.norns.calendar import MONTHS, iso, parse_long_date
from odin.norns.worst_case import WorstCase
from odin.state.models import Writeup

AI_LABEL = "AI-generated analysis"
CLAUSE_ID_RE = re.compile(r"\b[A-Z]{1,3}\d?:[A-Za-z0-9.\-]+|(?:§|Section|section|Clause)\s*[A-Z0-9]+(?:\.[0-9]+)*")
LONG_DATE_RE = re.compile(r"\b(" + "|".join(m.capitalize() for m in MONTHS) + r")\s+\d{1,2},\s*\d{4}\b")
ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
MONTH_YEAR_RE = re.compile(r"\b(" + "|".join(m.capitalize() for m in MONTHS) + r")\s+(\d{4})\b")
NUMBER_RE = re.compile(r"\$?\s?\d[\d,]*(?:\.\d+)?%?")


class WriteupOut(BaseModel):
    text: str


def summary_for_llm(wc: WorstCase, limit: int = 12) -> dict[str, Any]:
    """Top items only, each with its date, amount, contract and clause ids."""
    def clauses(cites: list[dict[str, Any]]) -> list[str]:
        return sorted({c["clause_id"] for c in cites if c.get("clause_id")})

    items = []
    for a in wc.accruals:
        if a.scenario == "worst_case" and a.category != "receivable_overdue":
            items.append({"date": iso(a.end or a.at), "contract": a.contract, "category": a.category, "amount": str(a.amount),
                          "what": a.description, "clauses": clauses(a.citations)})
    for u in wc.unquantified:
        if u["scenario"] == "worst_case":
            items.append({"date": u.get("at"), "contract": u["contract"], "category": u["category"], "amount": None,
                          "what": u["description"], "clauses": clauses(u["citations"])})
    # The largest quantified items and every unquantified right, in date order.
    quantified = sorted((i for i in items if i["amount"]), key=lambda i: Decimal(i["amount"]), reverse=True)[:limit]
    rights = [i for i in items if not i["amount"]][:limit]
    top = sorted(quantified + rights, key=lambda i: (i["date"] or "", i["contract"]))
    return {"as_of": iso(wc.as_of), "projection_end": iso(wc.projection_end),
            "total_worst_case": str(wc.total("worst_case")), "total_if_acting_on_time": str(wc.total("on_time")),
            "avoidable": str(wc.avoidable), "receivables_overdue": wc.kpis.get("receivables_overdue"), "items": top}


def allowed_tokens(data: Any) -> tuple[set[Decimal], set[str]]:
    """Every number and date that appears anywhere in the computed data."""
    numbers: set[Decimal] = set()
    dates: set[str] = set()
    blob = json.dumps(data, default=str)
    for d in ISO_DATE_RE.findall(blob):
        dates.add(d)
    blob_wo_dates = ISO_DATE_RE.sub(" ", blob)
    blob_wo_ids = CLAUSE_ID_RE.sub(" ", blob_wo_dates)
    for tok in NUMBER_RE.findall(blob_wo_ids):
        n = _num(tok)
        if n is not None:
            numbers.add(n)
            if "%" not in tok and n <= 1:
                numbers.add((n * 100).normalize())          # 0.15 in data may be written 15%
    for d in list(dates):
        y, m, _ = d.split("-")
        numbers.update({Decimal(y)})
    return numbers, dates


def _num(tok: str) -> Decimal | None:
    s = tok.replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return Decimal(s).normalize()
    except InvalidOperation:
        return None


def check_numbers(text: str, data: Any) -> list[str]:
    """Numbers and dates in the text that are not in the computed data (empty list = passes)."""
    numbers, dates = allowed_tokens(data)
    bad: list[str] = []
    rest = text
    for m in LONG_DATE_RE.finditer(text):
        d = parse_long_date(m.group(0))
        if d is None or d.isoformat() not in dates:
            bad.append(m.group(0))
    rest = LONG_DATE_RE.sub(" ", rest)
    for m in ISO_DATE_RE.finditer(rest):
        if m.group(0) not in dates:
            bad.append(m.group(0))
    rest = ISO_DATE_RE.sub(" ", rest)
    for m in MONTH_YEAR_RE.finditer(rest):
        month = MONTHS.index(m.group(1).lower()) + 1
        if not any(d.startswith(f"{m.group(2)}-{month:02d}") for d in dates):
            bad.append(m.group(0))
    rest = MONTH_YEAR_RE.sub(" ", rest)
    rest = CLAUSE_ID_RE.sub(" ", rest)
    for tok in NUMBER_RE.findall(rest):
        n = _num(tok)
        if n is not None and n not in numbers:
            bad.append(tok.strip())
    return bad


def template_writeup(summary: dict[str, Any]) -> str:
    lines = [f"Worst case as of {summary['as_of']} if no one acts (projected to {summary['projection_end']}): "
             f"${summary['total_worst_case']} of quantified exposure, of which ${summary['avoidable']} is avoidable by "
             f"acting on time."]
    for i in summary["items"]:
        amount = f" ${i['amount']}" if i["amount"] else " (not quantified by the contract)"
        refs = ", ".join(i["clauses"]) or i["contract"]
        lines.append(f"- {i['date'] or 'undated'} [{refs}]{amount}: {i['what']}")
    if summary.get("receivables_overdue") and Decimal(summary["receivables_overdue"]) > 0:
        lines.append(f"Receivables overdue to Quillhub: ${summary['receivables_overdue']} (not counted in the total).")
    return "\n".join(lines)


def generate(norns: Any, wc: WorstCase) -> Writeup:
    summary = summary_for_llm(wc)
    payload = json.dumps(summary, indent=1, default=str)
    cfg = norns.cfg.norns
    model = norns.llm.model if norns.llm else None
    tpl = norns.prompt("writeup")
    feedback = ""
    attempts: list[dict[str, Any]] = []
    if norns.llm is None:
        reason = "no LLM configured"
    else:
        reason = ""
        for attempt in range(2):
            values = {"summary": payload, "min_words": cfg.writeup_min_words, "max_words": cfg.writeup_max_words,
                      "feedback": feedback}
            prompt_hash = hashlib.sha256((tpl.system + "\n" + tpl.render(**values)).encode("utf-8")).hexdigest()
            try:
                out = norns.call_json(tpl, WriteupOut, purpose=f"norns.writeup:{iso(wc.as_of)}:{attempt + 1}", **values)
            except (LLMError, BudgetExceeded) as exc:
                reason = f"LLM unavailable: {type(exc).__name__}: {str(exc)[:160]}"
                break
            except Exception as exc:  # noqa: BLE001 - a writeup must never crash the run
                reason = f"LLM call failed: {type(exc).__name__}: {str(exc)[:160]}"
                break
            text = out.text.strip()
            words = len(text.split())
            bad = check_numbers(text, summary)
            attempts.append({"attempt": attempt + 1, "words": words, "unsupported": bad})
            if not bad and cfg.writeup_min_words * 0.8 <= words <= cfg.writeup_max_words * 1.2:
                return Writeup(as_of=iso(wc.as_of), label=AI_LABEL, generated_by="llm", text=text, model=model,  # type: ignore[arg-type]
                               prompt_hash=prompt_hash, check_passed=True, meta={"attempts": attempts})
            feedback = ("Your previous answer was rejected: " + (f"these numbers/dates are not in the data: {bad}. " if bad else "")
                        + (f"it had {words} words. " if not (cfg.writeup_min_words <= words <= cfg.writeup_max_words) else "")
                        + "Use only numbers and dates that appear in the data.")
            reason = "number/date check failed twice" if attempt == 1 else reason
    text = template_writeup(summary)
    return Writeup(as_of=iso(wc.as_of), label=f"Template writeup ({reason})", generated_by="template", text=text,  # type: ignore[arg-type]
                   model=model, prompt_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                   check_passed=not check_numbers(text, summary), meta={"attempts": attempts, "reason": reason})
