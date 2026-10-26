import React, { useState } from 'react';
import { CheckCircle2, Circle, ClipboardList, Loader2, Lock } from 'lucide-react';
import { SEVERITY, flatten, fmtCurrency, fmtDate } from '../common/format';

const COLUMN = {
  'Not Complete': { dot: '#FCFAF3', ring: '#727665', label: 'Not Complete' },
  'In Progress': { dot: '#C78A32', ring: '#C78A32', label: 'In Progress' },
  Completed: { dot: '#2E7D32', ring: '#2E7D32', label: 'Completed' },
};

function daysText(task) {
  if (task.status === 'Completed') return 'done';
  const n = task.days_left;
  if (n === null || n === undefined) return 'no due date';
  if (n < 0) return `overdue by ${-n} day${n === -1 ? '' : 's'}`;
  return n === 0 ? 'due today' : `${n} day${n === 1 ? '' : 's'} left`;
}

function shortTitle(task) {
  const month = task.period ? new Date(task.period + '-01T00:00:00').toLocaleDateString('en-US', { month: 'short' }) : null;
  if (task.kind === 'payment' && month) return `${month} fee`;
  if (task.kind === 'credit' && month) return `${month} credit claim`;
  return task.title;
}

function TaskCard({ task, statuses, busy, onSetStatus }) {
  const sev = SEVERITY[task.severity] || SEVERITY.low;
  const cite = task.citation || {};
  const locked = task.status_source === 'norns';
  return (
    <div className="rounded-lg border border-border-subtle bg-white p-3 space-y-2 shadow-xs relative overflow-hidden">
      <div className="absolute top-0 left-0 w-1 h-full" style={{ background: sev.bar }} />
      <div className="pl-1.5 space-y-1.5">
        <div className="flex items-start justify-between gap-2">
          <h4 className="text-xs font-bold text-dark-olive leading-snug">{task.title}</h4>
          <span className="font-mono text-[9px] font-bold px-1.5 py-0.5 rounded uppercase shrink-0" style={{ background: sev.bg, color: sev.text }}>
            {sev.label}
          </span>
        </div>
        <p className="font-mono text-[10px] text-secondary-olive leading-snug">
          {task.contract} · due {fmtDate(task.due_date)} · <span className={task.days_left < 0 && task.status !== 'Completed' ? 'text-odin-red font-semibold' : ''}>{daysText(task)}</span>
          {task.amount !== null && task.amount !== undefined && ` · ${fmtCurrency(task.amount, 0)}`}
        </p>
        {cite.clause_id && (
          <p className="font-mono text-[10px] text-primary-dark" title={flatten(cite.quote)}>
            <span className="px-1 py-0.5 rounded border border-border-subtle bg-cream">{cite.clause_id}</span>
            {cite.quote && <span className="text-secondary-olive"> “{flatten(cite.quote).slice(0, 70)}{flatten(cite.quote).length > 70 ? '…' : ''}”</span>}
          </p>
        )}
        {locked ? (
          <p className="font-mono text-[10px] text-[#2E7D32] flex items-center gap-1">
            <Lock className="w-3 h-3" /> NORNS marks it {task.norns_status?.replaceAll('_', ' ')}
          </p>
        ) : (
          <div className="flex items-center gap-1 pt-0.5">
            {statuses.map((s) => (
              <button
                key={s}
                onClick={() => s !== task.status && onSetStatus(task, s)}
                disabled={busy || s === task.status}
                className={`flex-1 px-1.5 py-1 rounded border font-mono text-[10px] transition-colors ${
                  s === task.status
                    ? 'bg-primary-dark text-cream border-primary-dark font-semibold'
                    : 'bg-cream/60 text-dark-olive border-border-subtle hover:bg-cream disabled:opacity-50'
                }`}
              >
                {busy && s !== task.status ? '…' : s === 'Not Complete' ? 'To do' : s === 'In Progress' ? 'Doing' : 'Done'}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TrackerRow({ label, tasks, asOf }) {
  const [info, setInfo] = useState('');
  const [selected, setSelected] = useState(null);
  const done = tasks.filter((t) => t.status === 'Completed').length;
  const pct = tasks.length ? Math.round((100 * done) / tasks.length) : 0;
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-semibold text-dark-olive">{label}</span>
        <span className="font-mono text-[11px] text-secondary-olive">{done}/{tasks.length} completed</span>
      </div>
      <div className="h-1 rounded bg-border-subtle overflow-hidden">
        <div className="h-full bg-[#2E7D32] transition-all duration-500" style={{ width: `${pct}%` }} />
      </div>
      <div className="relative flex items-center justify-between px-0.5 h-6">
        <div className="absolute left-2 right-2 top-1/2 h-0.5 bg-border-subtle" />
        {tasks.map((t) => {
          const col = COLUMN[t.status] || COLUMN['Not Complete'];
          const overdue = t.due_date && t.due_date < asOf && t.status !== 'Completed';
          const text = `${t.contract} ${shortTitle(t)} · ${fmtCurrency(t.amount, 0)} · due ${fmtDate(t.due_date)} · ${t.status}`;
          return (
            <button
              key={t.task_id}
              title={text}
              aria-label={text}
              onClick={() => {
                setInfo(text);
                setSelected(t.task_id);
              }}
              className="relative w-4 h-4 rounded-full border-2 transition-transform hover:scale-125"
              style={{
                background: col.dot,
                borderColor: overdue ? '#C83D3D' : col.ring,
                outline: selected === t.task_id ? '2px solid #727665' : 'none',
                outlineOffset: 2,
              }}
            />
          );
        })}
      </div>
      <p className="min-h-[16px] font-mono text-[11px] text-secondary-olive" aria-live="polite">{info}</p>
    </div>
  );
}

export default function HeimdallTaskBoard({ tasks, asOf, statuses, processLabels, busyTaskId, onSetStatus }) {
  const contracts = [...new Set(tasks.map((t) => t.contract))].sort();
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
      {/* Kanban */}
      <section className="lg:col-span-8 rounded-lg border border-border-subtle bg-ivory p-4 shadow-sm space-y-3">
        <div>
          <h2 className="font-bold text-dark-olive flex items-center gap-2">
            <ClipboardList className="w-4 h-4 text-primary" /> Task board
          </h2>
          <p className="font-mono text-[10px] text-secondary-olive mt-0.5">
            One card per NORNS obligation overdue or due within 60 days · completing a payment records it and recomputes NORNS
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {statuses.map((status) => {
            const mine = tasks.filter((t) => t.status === status);
            const col = COLUMN[status] || COLUMN['Not Complete'];
            return (
              <div key={status} className="rounded-lg bg-[#FAF6EC] border border-border-subtle p-2.5 space-y-2 min-h-[120px]">
                <div className="flex items-center justify-between font-mono text-[11px] font-bold text-primary-dark px-0.5">
                  <span className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full border-2" style={{ background: col.dot, borderColor: col.ring }} />
                    {status}
                  </span>
                  <span className="text-secondary-olive">{mine.length}</span>
                </div>
                {mine.length === 0 ? (
                  <p className="text-center py-4 font-mono text-[10px] text-secondary-olive">—</p>
                ) : (
                  mine.map((t) => (
                    <TaskCard key={t.task_id} task={t} statuses={statuses} busy={busyTaskId === t.task_id} onSetStatus={onSetStatus} />
                  ))
                )}
              </div>
            );
          })}
        </div>
        {busyTaskId && (
          <p className="font-mono text-[11px] text-secondary-olive flex items-center gap-1.5">
            <Loader2 className="w-3 h-3 animate-spin" /> Saving and recomputing NORNS…
          </p>
        )}
      </section>

      {/* Progress tracker */}
      <section className="lg:col-span-4 rounded-lg border border-border-subtle bg-ivory p-4 shadow-sm space-y-4">
        <div>
          <h2 className="font-bold text-dark-olive flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-[#2E7D32]" /> Progress by contract
          </h2>
          <p className="font-mono text-[10px] text-secondary-olive mt-0.5 flex items-center gap-2 flex-wrap">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#2E7D32]" /> done</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[#C78A32]" /> in progress</span>
            <span className="flex items-center gap-1"><Circle className="w-2.5 h-2.5" /> to do</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full border-2 border-odin-red" /> overdue</span>
          </p>
        </div>
        {contracts.length === 0 ? (
          <p className="font-mono text-xs text-secondary-olive">No tasks on this date.</p>
        ) : (
          contracts.map((c) => (
            <TrackerRow
              key={c}
              label={processLabels?.[c] || c}
              tasks={tasks.filter((t) => t.contract === c).sort((a, b) => (a.due_date || '').localeCompare(b.due_date || ''))}
              asOf={asOf}
            />
          ))
        )}
      </section>
    </div>
  );
}
