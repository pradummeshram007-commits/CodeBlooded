"""Plain-text rendering of Norns results for the scripts (no logic here)."""
from __future__ import annotations

from typing import Any

from odin.norns.clock import Changes
from odin.norns.engine import Inst, Timeline
from odin.norns.worst_case import WorstCase


def _inst(i: Inst | dict[str, Any]) -> str:
    v = i.view() if isinstance(i, Inst) else i
    amount = f" {v['amount']}" if v.get("amount") else ""
    out = f" outstanding {v['outstanding']}" if v.get("status") in ("unpaid", "partial") else ""
    days = f" ({v['days_remaining']:+d} d)" if v.get("days_remaining") is not None else ""
    sev = f" [{v['severity']}]" if v.get("severity") else ""
    return f"{v['due'] or '-':<10} {v['contract']:<3} {v['status']:<12} {v['name']}{amount}{out}{days}{sev}"


def timeline_text(t: Timeline, due_soon: int = 7, n_next: int = 5) -> str:
    lines = [f"== Norns as of {t.as_of} (contracts {', '.join(t.contracts)})"]
    over, now = t.overdue(), t.due_now(due_soon)
    lines.append(f"Overdue ({len(over)}):" + ("" if over else " none"))
    lines += ["  " + _inst(i) for i in over]
    lines.append(f"Due now, within {due_soon} days ({len(now)}):" + ("" if now else " none"))
    lines += ["  " + _inst(i) for i in now]
    nxt = t.upcoming(n_next)
    lines.append(f"Next {len(nxt)} deadlines:")
    lines += ["  " + _inst(i) for i in nxt]
    lines.append("Renewal-notice deadlines:")
    for c, v in t.renewal_deadlines().items():
        lines.append(f"  {c}: {v['due']} ({v['status']}, {v['days_remaining']} days left; calendar {v['due_calendar']}, "
                     f"business {v['due_business']}) - {v['name']}")
    if t.penalty_triggers:
        lines.append("Penalty triggers:")
        lines += [f"  {p['date']} {p['contract']} {p['type']}: {p['description']}" + (f" ({p['amount']})" if p.get("amount") else "")
                  for p in t.penalty_triggers]
    paid = [i for i in t.payments() if i.status in ("paid_on_time", "paid_late", "partial")]
    lines.append(f"Past payments matched to the ledger: {len(paid)} "
                 f"({sum(1 for i in paid if i.status == 'paid_on_time')} on time, "
                 f"{sum(1 for i in paid if i.status == 'paid_late')} late, {sum(1 for i in paid if i.status == 'partial')} partial)")
    if t.unmatched_ledger:
        lines.append("Unmatched ledger rows (kept, flagged):")
        lines += [f"  line {r['line_no']} {r['date']} {r['amount']} {r['reference']}: {r['why']}" for r in t.unmatched_ledger]
    if t.out_of_scope_ledger:
        lines.append(f"Ledger rows outside Norns' contracts: {len(t.out_of_scope_ledger)} "
                     f"({', '.join(sorted({str(r['contract_id']) for r in t.out_of_scope_ledger}))})")
    return "\n".join(lines)


def worst_case_text(wc: WorstCase) -> str:
    k = wc.kpis
    lines = [f"== Worst case as of {wc.as_of} (no action until {wc.projection_end})",
             f"Total worst case ${k['total_worst_case']} | acting on time ${k['total_on_time']} | avoidable "
             f"${k['total_avoidable']} | receivables overdue ${k['receivables_overdue']} (not in the total)"]
    for a in sorted((a for a in wc.accruals if a.scenario == "worst_case"), key=lambda a: (a.at, a.contract)):
        cites = ", ".join(sorted({c["clause_id"] or c["doc_id"] for c in a.citations if c.get("clause_id") or c.get("doc_id")}))
        lines.append(f"  {a.amount:>12} {a.contract:<3} {a.category:<22} {a.description}  [{cites}]")
        lines.append(f"{'':>16}formula: {a.formula}; inputs: {a.inputs}")
    unq = [u for u in wc.unquantified if u["scenario"] == "worst_case"]
    if unq:
        lines.append("Unquantified (the contract gives no number):")
        for u in sorted(unq, key=lambda u: (u.get("at") or "", u["contract"])):
            cites = ", ".join(sorted({c["clause_id"] or c["doc_id"] for c in u["citations"] if c.get("clause_id") or c.get("doc_id")}))
            lines.append(f"  {u.get('at') or '-':<10} {u['contract']:<3} {u['category']:<18} {u['description']}  [{cites}]")
    if wc.flags:
        lines.append("Worst-case notes:")
        lines += [f"  - {f}" for f in wc.flags]
    return "\n".join(lines)


def changes_text(ch: Changes) -> str:
    if ch.empty():
        return f"{ch.from_as_of} -> {ch.to_as_of}: no change"
    lines = [f"{ch.from_as_of} -> {ch.to_as_of}:"]
    lines += [f"  newly overdue: {_inst(v)}" for v in ch.newly_overdue]
    lines += [f"  penalty triggered: {p['contract']} {p['type']} ({p['date']}): {p['description']}" for p in ch.penalties_triggered]
    lines += [f"  deadline passed: {v['due']} {v['contract']} {v['name']} -> {v['outcome']}" for v in ch.deadlines_passed]
    lines += [f"  RENEWAL LOCKED IN: {v['contract']} {v['name']}" for v in ch.renewals_locked_in]
    return "\n".join(lines)
