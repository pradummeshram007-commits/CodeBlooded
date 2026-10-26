"""The Heimdall progress tracker: one row per contract, its tasks as checkpoint dots on a line.

    html = tracker_html(rows, dark=False)
    components.html(html, height=tracker_height(rows))

Dots: Completed = filled (with a short "cleared" animation when it just changed), In Progress = amber,
Not Complete = empty, overdue = red outline. Clicking a dot shows one line under its row.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field


@dataclass
class Dot:
    task_id: str
    status: str            # Not Complete | In Progress | Completed
    overdue: bool
    info: str              # "A1 May fee · $8,000 · due 2 Jun 2027 · In Progress"
    cleared: bool = False  # just changed to Completed: play the animation once


@dataclass
class Row:
    label: str             # "A1 · StratoNode hosting"
    dots: list[Dot] = field(default_factory=list)

    @property
    def done(self) -> int:
        return sum(1 for d in self.dots if d.status == "Completed")


_CLASS = {"Completed": "done", "In Progress": "progress", "Not Complete": "todo"}

_CSS = """
:root { --fg:#1f2937; --muted:#6b7280; --line:#d1d5db; --empty:#ffffff; --done:#16a34a; --amber:#f59e0b;
        --red:#dc2626; --bar:#e5e7eb; }
.dark { --fg:#e5e7eb; --muted:#9ca3af; --line:#4b5563; --empty:#0e1117; --bar:#374151; }
body { margin:0; background:transparent; font-family:"Source Sans Pro",system-ui,sans-serif; }
.trk { color:var(--fg); padding:2px 4px; }
.row { margin:0 0 14px; }
.head { display:flex; justify-content:space-between; align-items:baseline; font-size:14px; margin-bottom:4px; }
.label { font-weight:600; }
.count { color:var(--muted); font-size:12px; }
.bar { height:4px; border-radius:2px; background:var(--bar); overflow:hidden; margin-bottom:8px; }
.fill { height:100%; background:var(--done); transition:width .6s ease; }
.line { position:relative; display:flex; justify-content:space-between; align-items:center; padding:0 2px; height:22px; }
.line::before { content:""; position:absolute; left:8px; right:8px; top:50%; height:2px; background:var(--line); }
.dot { position:relative; width:16px; height:16px; border-radius:50%; border:2px solid var(--muted); background:var(--empty);
       cursor:pointer; padding:0; box-sizing:border-box; }
.dot.done { background:var(--done); border-color:var(--done); }
.dot.progress { background:var(--amber); border-color:var(--amber); }
.dot.overdue { border-color:var(--red); }
.dot.sel { outline:2px solid var(--muted); outline-offset:2px; }
.dot.cleared { animation: fill .7s ease-out, pulse 1.1s ease-out .7s 2; }
@keyframes fill { from { background:var(--empty); transform:scale(.6); } 60% { transform:scale(1.25); }
                  to { background:var(--done); transform:scale(1); } }
@keyframes pulse { from { box-shadow:0 0 0 0 rgba(22,163,74,.55); } to { box-shadow:0 0 0 10px rgba(22,163,74,0); } }
.info { min-height:18px; font-size:13px; color:var(--muted); margin-top:6px; }
"""

_JS = """
document.querySelectorAll('.dot').forEach(function (d) {
  d.addEventListener('click', function () {
    var row = d.closest('.row');
    row.querySelector('.info').textContent = d.dataset.info;
    row.querySelectorAll('.dot').forEach(function (x) { x.classList.toggle('sel', x === d); });
  });
});
"""


def tracker_html(rows: list[Row], *, dark: bool = False) -> str:
    parts = []
    for r in rows:
        total = len(r.dots)
        pct = round(100 * r.done / total) if total else 0
        dots = "".join(
            f'<button class="dot {_CLASS.get(d.status, "todo")}{" overdue" if d.overdue and d.status != "Completed" else ""}'
            f'{" cleared" if d.cleared else ""}" title="{html.escape(d.info)}" data-info="{html.escape(d.info)}" '
            f'aria-label="{html.escape(d.info)}"></button>' for d in r.dots)
        parts.append(
            f'<div class="row"><div class="head"><span class="label">{html.escape(r.label)}</span>'
            f'<span class="count">{r.done}/{total} completed</span></div>'
            f'<div class="bar"><div class="fill" style="width:{pct}%"></div></div>'
            f'<div class="line">{dots}</div><div class="info" aria-live="polite"></div></div>')
    body = "".join(parts) or '<div class="info">No tasks.</div>'
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>'
            f'<body class="{"dark" if dark else ""}"><div class="trk">{body}</div><script>{_JS}</script></body></html>')


def tracker_height(rows: list[Row]) -> int:
    return 24 + 78 * max(len(rows), 1)
