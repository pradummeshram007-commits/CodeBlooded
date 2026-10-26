"""Heimdall: alerts, the task board and the progress tracker for one clock date.

Reads heimdall_events / heimdall_alerts / heimdall_tasks (written by scripts/run_heimdall.py) and writes
only the board's status tags. Never calls the LLM: Heimdall is constructed without an LLM client, and a
tag change recomputes Norns (pure Python) with the users' payment facts. Re-reads the database after every
change and every 10 seconds, so teammates see each other's changes.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # app/ (for ui), which adds the repo root

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from streamlit_autorefresh import st_autorefresh  # noqa: E402

from heimdall_tracker import Dot, Row, tracker_height, tracker_html  # noqa: E402
from ui import runtime_or_stop  # noqa: E402
from odin.agents.heimdall import SEVERITY_RANK, TASK_STATUSES, Heimdall  # noqa: E402
from odin.state.models import HeimdallTask  # noqa: E402
from odin.viewer import contract_link  # noqa: E402

st.set_page_config(page_title="Heimdall · Odin", page_icon="🛡️", layout="wide")
st_autorefresh(interval=10_000, key="heimdall-autorefresh")
rt = runtime_or_stop()
store = rt.store

SEVERITY_COLORS = {"critical": "red", "high": "orange", "medium": "yellow", "low": "blue"}
COLUMN_ICONS = {"Not Complete": "⚪", "In Progress": "🟠", "Completed": "🟢"}


@st.cache_resource(show_spinner="Loading Norns…")
def _heimdall() -> Heimdall:
    return Heimdall(rt.store, None, rt.cfg, files=rt.files)       # no LLM client: the page never calls the LLM


def money(amount: Decimal | None) -> str:
    if amount is None:
        return "—"
    sign, amount = ("-" if amount < 0 else ""), abs(amount)      # "-$7,256": st.metric reads the sign first
    return sign + (f"${amount:,.0f}" if amount == amount.to_integral_value() else f"${amount:,.2f}")


def long_date(iso_day: str | None) -> str:
    if not iso_day:
        return "no due date"
    d = date.fromisoformat(iso_day)
    return f"{d.day} {d:%b %Y}"


def days_left(task: HeimdallTask, today: date) -> str:
    if not task.due_date:
        return ""
    n = (date.fromisoformat(task.due_date) - today).days
    if task.status == "Completed":
        return "done"
    if n < 0:
        return f"overdue by {-n} day{'s' if n != -1 else ''}"
    return "due today" if n == 0 else f"{n} day{'s' if n != 1 else ''} left"


def short_title(task: HeimdallTask) -> str:
    if task.kind == "payment" and task.period:
        return f"{date.fromisoformat(task.period + '-01'):%b} fee"
    if task.kind == "credit" and task.period:
        return f"{date.fromisoformat(task.period + '-01'):%b} credit claim"
    return task.title


def card_severity(task: HeimdallTask, alerts_by_instance: dict[str, str], heimdall: Heimdall, today: date) -> str:
    if task.status == "Completed":
        return "done"
    if task.task_id in alerts_by_instance:
        return alerts_by_instance[task.task_id]
    days = (date.fromisoformat(task.due_date) - today).days if task.due_date else None
    return "critical" if days is not None and days < 0 else heimdall.severity_for(days, renewal=task.kind == "renewal")


def set_status(heimdall: Heimdall, as_of: str, task: HeimdallTask, status: str) -> None:
    ok, msg = heimdall.set_task_status(as_of, task.task_id, status)
    st.session_state["flash"] = ("success" if ok else "error", msg)


heimdall = _heimdall()
runs = store.heimdall_runs()
st.title("Heimdall — events, alerts and tasks")
if not runs:
    st.info("No Heimdall run yet. Run `python scripts/run_heimdall.py --drop 1 --checkpoint 1` first.")
    st.stop()
dates = sorted({a for a, _d in runs}, reverse=True)
as_of = st.selectbox("Clock date", dates, index=0, help="Each Heimdall run is stored per clock date.") if len(dates) > 1 \
    else dates[0]
today = date.fromisoformat(as_of)
kind, msg = st.session_state.pop("flash", (None, None))
if kind:
    (st.success if kind == "success" else st.error)(msg)

# ----------------------------------------------------------------------- top: clock, worst case, alert strip

live = heimdall.totals(as_of)
alerts = store.list_heimdall_alerts(as_of)
tasks = store.list_heimdall_tasks(as_of)
c1, c2, c3 = st.columns([1, 1.4, 2])
c1.metric("Clock date", long_date(as_of))
c2.metric("Worst-case exposure", money(live.live), delta=f"{money(live.live - live.after_events)} from task tags"
          if live.live != live.after_events else None, delta_color="inverse",
          help=f"Norns' worst case on the clock date: {money(live.baseline)} without event facts, "
               f"{money(live.after_events)} with them; task tags add the users' payment facts.")
counts = {s: sum(1 for a in alerts if a.severity == s) for s in SEVERITY_RANK}
c3.markdown("**Alerts** " + " ".join(f":{SEVERITY_COLORS[s]}-badge[{counts[s]} {s}]" for s in SEVERITY_RANK))

with st.container(border=True):
    for a in alerts:
        st.markdown(f":{SEVERITY_COLORS[a.severity]}-badge[{a.severity}] {a.message} "
                    f"<span style='opacity:.6'>({a.clause_id or '—'})</span>", unsafe_allow_html=True)
    if not alerts:
        st.caption("No alerts on this date.")
    if st.toggle("show filtered noise", key="show-noise"):
        for e in heimdall.event_rows(as_of):
            if e.status == "noise":
                st.markdown(f":gray-badge[noise] **{e.event_id}** {e.subject or ''} — {e.noise_reason}")

# ----------------------------------------------------------------------- Kanban

st.subheader("Task board")
alerts_by_instance: dict[str, str] = {}
for a in alerts:
    if a.instance_key and SEVERITY_RANK[a.severity] > SEVERITY_RANK.get(alerts_by_instance.get(a.instance_key, ""), 0):
        alerts_by_instance[a.instance_key] = a.severity
columns = st.columns(3)
for col, status in zip(columns, TASK_STATUSES):
    mine = [t for t in tasks if t.status == status]
    col.markdown(f"#### {COLUMN_ICONS[status]} {status} · {len(mine)}")
    for t in mine:
        with col.container(border=True):
            sev = card_severity(t, alerts_by_instance, heimdall, today)
            badge = ":gray-badge[done]" if sev == "done" else f":{SEVERITY_COLORS[sev]}-badge[{sev}]"
            st.markdown(f"**{t.title}** {badge}")
            st.caption(f"{t.contract} · due {long_date(t.due_date)} · {days_left(t, today)} · {money(t.amount)}")
            cite = t.citation or {}
            if cite.get("clause_id"):
                link = contract_link(cite.get("doc_id") or cite["clause_id"].split(":", 1)[0], cite["clause_id"],
                                     cite.get("quote"))
                st.markdown(f"[See the contract]({link}) · {cite['clause_id']}")
            if t.status_source == "norns":
                st.caption(f"🔒 Norns marks it {t.norns_status}")
            else:
                with st.popover("Set status", key=f"pop-{t.task_id}"):
                    for target in TASK_STATUSES:
                        st.button(target, key=f"set-{t.task_id}-{target}", disabled=target == t.status,
                                  on_click=set_status, args=(heimdall, as_of, t, target), width="stretch")
    if not mine:
        col.caption("—")

# ----------------------------------------------------------------------- progress tracker

st.subheader("Progress")
previous = st.session_state.get("tracker-previous", {})
rows = []
for contract in sorted({t.contract for t in tasks}):
    row = Row(heimdall.process_label(contract))
    for t in sorted((x for x in tasks if x.contract == contract), key=lambda x: (x.due_date or "", x.task_id)):
        overdue = bool(t.due_date and t.due_date < as_of and t.status != "Completed")
        info = f"{t.contract} {short_title(t)} · {money(t.amount)} · due {long_date(t.due_date)} · {t.status}"
        cleared = t.status == "Completed" and previous.get(t.task_id) not in (None, "Completed")
        row.dots.append(Dot(t.task_id, t.status, overdue, info, cleared))
    rows.append(row)
st.session_state["tracker-previous"] = {t.task_id: t.status for t in tasks}
dark = getattr(getattr(st.context, "theme", None), "type", None) == "dark"
components.html(tracker_html(rows, dark=dark), height=tracker_height(rows))
st.caption("Refreshes every 10 seconds; every tag change is saved at once and recomputes Norns' worst case.")
