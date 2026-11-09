import { livePoll } from '../utils/live';
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, Check, X, Edit2, Clock, Keyboard } from 'lucide-react';
import { api, ApiError } from '../api/client';
import type { HealProposalRow, ToolCallRow } from '../api/types';
import { Panel } from '../components/Panel';
import { JsonEditor } from '../components/JsonEditor';
import { useToast } from '../components/Toast';

type CardKey = `tool-${number}` | `heal-${number}`;

/** "12s", "3m 05s": how long a card has been waiting. */
export function formatWaiting(createdAt: string, now: number): string {
  const secs = Math.max(0, Math.floor((now - new Date(createdAt).getTime()) / 1000));
  if (secs < 60) return `${secs}s`;
  return `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, '0')}s`;
}

/** Oldest first. Tool calls and heal proposals share one keyboard order: tool calls, then heals. */
export function orderCards(calls: ToolCallRow[], heals: HealProposalRow[]): CardKey[] {
  const byAge = <T extends { created_at: string; id: number }>(a: T, b: T) =>
    a.created_at.localeCompare(b.created_at) || a.id - b.id;
  return [
    ...[...calls].sort(byAge).map((c) => `tool-${c.id}` as CardKey),
    ...[...heals].sort(byAge).map((h) => `heal-${h.id}` as CardKey),
  ];
}

const btn = (bg: string, border: string, color: string): React.CSSProperties => ({
  display: 'flex',
  alignItems: 'center',
  gap: 'var(--space-1)',
  padding: 'var(--space-2) var(--space-3)',
  backgroundColor: bg,
  border: `1px solid ${border}`,
  color,
  borderRadius: 'var(--radius-sm)',
  fontWeight: 600,
  fontSize: 'var(--type-micro-size)',
  // The panel clips its overflow, so a button that is squeezed instead of wrapped
  // would end up cut off — and a cut-off button cannot be clicked. Keeping the
  // buttons at their natural width makes the row wrap onto a second line.
  flexShrink: 0,
});

const cardStyle = (selected: boolean): React.CSSProperties => ({
  backgroundColor: 'var(--color-surface-elevated)',
  border: `1px solid ${selected ? 'var(--color-accent)' : 'var(--color-border)'}`,
  boxShadow: selected ? '0 0 0 1px var(--color-accent)' : 'none',
  borderRadius: 'var(--radius-sm)',
  padding: 'var(--space-4)',
  display: 'flex',
  flexDirection: 'column',
  gap: 'var(--space-3)',
});

interface ToolCardProps {
  call: ToolCallRow;
  selected: boolean;
  now: number;
  rewriting: boolean;
  busy: boolean;
  onSelect: () => void;
  onDecide: (decision: 'allow' | 'deny') => void;
  onStartRewrite: () => void;
  onCancelRewrite: () => void;
  onSendRewrite: (args: Record<string, unknown>) => void;
}

const ToolCard: React.FC<ToolCardProps> = ({
  call,
  selected,
  now,
  rewriting,
  busy,
  onSelect,
  onDecide,
  onStartRewrite,
  onCancelRewrite,
  onSendRewrite,
}) => {
  const [draft, setDraft] = useState(JSON.stringify(call.args, null, 2));
  const [parsed, setParsed] = useState<Record<string, unknown> | null>(call.args);
  const [valid, setValid] = useState(true);

  return (
    <div
      data-testid={`tool-card-${call.id}`}
      data-selected={selected}
      onClick={onSelect}
      style={cardStyle(selected)}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 'var(--space-3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{call.agent_id}</span>
          <span style={{ color: 'var(--color-text-muted)' }}>called</span>
          <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>{call.tool_name}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          <span
            className="tabular-nums"
            style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--color-text-muted)', fontSize: 'var(--type-micro-size)' }}
          >
            <Clock size={12} /> waiting {formatWaiting(call.created_at, now)}
          </span>
          {call.value_usd > 0 && (
            <span
              className="tabular-nums"
              style={{
                backgroundColor: 'var(--color-state-suspicious-bg)',
                color: 'var(--color-state-suspicious)',
                padding: '2px 8px',
                borderRadius: 'var(--radius-sm)',
                fontWeight: 700,
                fontSize: 'var(--type-micro-size)',
              }}
            >
              ${call.value_usd.toFixed(2)} at stake
            </span>
          )}
        </div>
      </div>

      {call.reason && (
        <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)' }}>
          Policy: {call.reason}
        </p>
      )}

      {rewriting ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
          <JsonEditor
            value={draft}
            minHeight="140px"
            dataTestId={`rewrite-editor-${call.id}`}
            onChange={(v, ok, p) => {
              setDraft(v);
              setValid(ok);
              setParsed(p);
            }}
          />
          <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
            <button type="button" aria-label="Cancel rewrite" onClick={onCancelRewrite} style={btn('var(--color-surface)', 'var(--color-border)', 'var(--color-text-primary)')}>
              Cancel
            </button>
            <button
              type="button"
              aria-label="Send rewrite"
              disabled={!valid || !parsed || busy}
              onClick={() => parsed && onSendRewrite(parsed)}
              style={{ ...btn('var(--color-state-probation-bg)', 'var(--color-state-probation-border)', 'var(--color-state-probation)'), opacity: !valid || busy ? 0.5 : 1 }}
            >
              <Edit2 size={14} /> Send rewrite
            </button>
          </div>
        </div>
      ) : (
        <>
          <pre
            style={{
              backgroundColor: 'var(--color-canvas)',
              padding: 'var(--space-3)',
              borderRadius: 'var(--radius-sm)',
              fontSize: 'var(--type-micro-size)',
              fontFamily: 'var(--font-mono)',
              overflowX: 'auto',
            }}
          >
            {JSON.stringify(call.args, null, 2)}
          </pre>
          <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <button type="button" aria-label={`Approve tool call ${call.id}`} disabled={busy} onClick={() => onDecide('allow')} style={btn('var(--color-state-healthy-bg)', 'var(--color-state-healthy-border)', 'var(--color-state-healthy)')}>
              <Check size={14} /> Approve (A)
            </button>
            <button type="button" aria-label={`Deny tool call ${call.id}`} disabled={busy} onClick={() => onDecide('deny')} style={btn('var(--color-state-killed-bg)', 'var(--color-state-killed-border)', 'var(--color-state-killed-text)')}>
              <X size={14} /> Deny (D)
            </button>
            <button type="button" aria-label={`Rewrite tool call ${call.id}`} disabled={busy} onClick={onStartRewrite} style={btn('var(--color-surface)', 'var(--color-border)', 'var(--color-text-primary)')}>
              <Edit2 size={14} /> Rewrite (R)
            </button>
          </div>
        </>
      )}
    </div>
  );
};

/** Ops of a memory patch as `key: old → new`; a tool policy patch as raw JSON. */
const HealCard: React.FC<{
  heal: HealProposalRow;
  selected: boolean;
  now: number;
  busy: boolean;
  onSelect: () => void;
  onDecide: (d: 'apply' | 'reject') => void;
}> = ({ heal, selected, now, busy, onSelect, onDecide }) => {
  const { data: memory } = useQuery({
    queryKey: ['memory', heal.agent_id],
    queryFn: () => api.getMemory(heal.agent_id),
    enabled: heal.kind === 'memory_patch',
  });
  const ops = (heal.patch as { memory?: { op: string; key: string; value?: unknown }[] }).memory ?? [];
  const oldOf = (k: string) => (memory?.content as Record<string, unknown> | undefined)?.[k];
  const show = (v: unknown) => (v === undefined ? '(unset)' : typeof v === 'string' ? v : JSON.stringify(v));

  return (
    <div data-testid={`heal-card-${heal.id}`} data-selected={selected} onClick={onSelect} style={cardStyle(selected)}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>heal · {heal.agent_id}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          <span className="tabular-nums" style={{ color: 'var(--color-text-muted)', fontSize: 'var(--type-micro-size)' }}>
            waiting {formatWaiting(heal.created_at, now)}
          </span>
          <span
            style={{
              backgroundColor: 'var(--color-state-probation-bg)',
              color: 'var(--color-state-probation)',
              padding: '2px 8px',
              borderRadius: 'var(--radius-sm)',
              fontWeight: 700,
              fontSize: 'var(--type-micro-size)',
            }}
          >
            {Math.round(heal.confidence * 100)}% Confidence
          </span>
        </div>
      </div>
      <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)' }}>{heal.reason}</p>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--type-micro-size)', backgroundColor: 'var(--color-canvas)', padding: 'var(--space-3)', borderRadius: 'var(--radius-sm)' }}>
        {heal.kind === 'memory_patch' ? (
          ops.map((o, i) => (
            <div key={i}>
              {o.key}: {show(oldOf(o.key))} → {o.op === 'delete' ? '(removed)' : show(o.value)}
            </div>
          ))
        ) : (
          <pre>{JSON.stringify(heal.patch, null, 2)}</pre>
        )}
      </div>
      <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
        <button type="button" aria-label={`Apply heal ${heal.id}`} disabled={busy} onClick={() => onDecide('apply')} style={btn('var(--color-state-healthy-bg)', 'var(--color-state-healthy-border)', 'var(--color-state-healthy)')}>
          <Check size={14} /> Apply (A)
        </button>
        <button type="button" aria-label={`Reject heal ${heal.id}`} disabled={busy} onClick={() => onDecide('reject')} style={btn('var(--color-state-killed-bg)', 'var(--color-state-killed-border)', 'var(--color-state-killed-text)')}>
          <X size={14} /> Reject (D)
        </button>
      </div>
    </div>
  );
};

export const ApprovalsView: React.FC = () => {
  const qc = useQueryClient();
  const toast = useToast();
  const [selected, setSelected] = useState<CardKey | null>(null);
  const [rewriting, setRewriting] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const { data: calls, isLoading: loadingCalls, error: errorCalls, refetch: refetchCalls } = useQuery({
    queryKey: ['tool-calls', 'pending'],
    queryFn: () => api.getToolCalls('pending'),
    refetchInterval: livePoll,
  });
  const { data: heals, isLoading: loadingHeals, error: errorHeals, refetch: refetchHeals } = useQuery({
    queryKey: ['heal-proposals', 'pending'],
    queryFn: () => api.getHealProposals('pending'),
    refetchInterval: livePoll,
  });

  const pendingCalls = useMemo(
    () => [...(calls?.items ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id),
    [calls]
  );
  const pendingHeals = useMemo(
    () => [...(heals?.items ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at) || a.id - b.id),
    [heals]
  );
  const order = useMemo(() => orderCards(pendingCalls, pendingHeals), [pendingCalls, pendingHeals]);

  // keep the selection valid as cards leave
  useEffect(() => {
    if (order.length === 0) setSelected(null);
    else if (!selected || !order.includes(selected)) setSelected(order[0]);
  }, [order, selected]);

  const onError = (e: unknown) =>
    toast.error('Decision failed', e instanceof ApiError ? e.detail : e instanceof Error ? e.message : 'Unknown error');
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['tool-calls'] });
    qc.invalidateQueries({ queryKey: ['heal-proposals'] });
    qc.invalidateQueries({ queryKey: ['roi'] });
  };

  const toolMut = useMutation({
    mutationFn: (v: { id: number; decision: 'allow' | 'deny' | 'rewrite'; final_args?: Record<string, unknown> }) =>
      api.decideToolCall(v.id, {
        decision: v.decision,
        final_args: v.final_args ?? null,
        decided_by: 'human',
        reason: `${v.decision} from approvals inbox`,
      }),
    onSuccess: (_d, v) => {
      toast.success(`Tool call ${v.id} ${v.decision === 'allow' ? 'approved' : v.decision === 'deny' ? 'denied' : 'rewritten'}`);
      setRewriting(null);
      refresh();
    },
    onError,
  });
  const healMut = useMutation({
    mutationFn: (v: { id: number; decision: 'apply' | 'reject' }) =>
      api.decideHealProposal(v.id, { decision: v.decision, reason: `${v.decision} from approvals inbox`, requested_by: 'human' }),
    onSuccess: (_d, v) => {
      toast.success(`Heal proposal ${v.id} ${v.decision === 'apply' ? 'applied' : 'rejected'}`);
      refresh();
    },
    onError,
  });
  const busy = toolMut.isPending || healMut.isPending;

  const decideSelected = useCallback(
    (kind: 'approve' | 'deny' | 'rewrite') => {
      if (!selected || busy) return;
      const id = Number(selected.split('-')[1]);
      if (selected.startsWith('tool-')) {
        if (kind === 'rewrite') setRewriting(id);
        else toolMut.mutate({ id, decision: kind === 'approve' ? 'allow' : 'deny' });
      } else if (kind !== 'rewrite') {
        healMut.mutate({ id, decision: kind === 'approve' ? 'apply' : 'reject' });
      }
    },
    [selected, busy, toolMut, healMut]
  );

  // Keyboard: J/K move, A approve/apply, D deny/reject, R rewrite. Ignored while typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'j' || k === 'k') {
        if (order.length === 0) return;
        const i = selected ? order.indexOf(selected) : -1;
        const next = k === 'j' ? Math.min(order.length - 1, i + 1) : Math.max(0, i - 1);
        setSelected(order[next]);
        setRewriting(null);
        e.preventDefault();
      } else if (k === 'a') decideSelected('approve');
      else if (k === 'd') decideSelected('deny');
      else if (k === 'r') decideSelected('rewrite');
      else if (k === 'escape') setRewriting(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [order, selected, decideSelected]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', width: '100%' }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 'var(--space-4)', flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ fontSize: 'var(--type-title-sm-size)', fontWeight: 700, color: 'var(--color-text-primary)' }}>
            Human-in-the-Loop Approvals Inbox
          </h1>
          <p style={{ fontSize: 'var(--type-body-sm-size)', color: 'var(--color-text-secondary)', marginTop: 'var(--space-1)' }}>
            Review, approve, deny, or rewrite high-risk tool calls and memory patches.
          </p>
        </div>
        <div
          aria-label="Keyboard shortcuts"
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', fontFamily: 'var(--font-mono)', fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}
        >
          <Keyboard size={14} />
          <span>J/K move</span>
          <span>A approve</span>
          <span>D deny</span>
          <span>R rewrite</span>
        </div>
      </header>

      <Panel
        title={`Pending Tool Overrides (${pendingCalls.length})`}
        icon={<ShieldAlert size={18} />}
        loading={loadingCalls}
        error={errorCalls}
        empty={pendingCalls.length === 0}
        emptyTitle="Nothing waiting for a human"
        emptyMessage="No tool calls currently held by policy gates. Calls exceeding monetary limits will appear here."
        onRetry={() => refetchCalls()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {pendingCalls.map((call) => (
            <ToolCard
              key={call.id}
              call={call}
              now={now}
              selected={selected === `tool-${call.id}`}
              rewriting={rewriting === call.id}
              busy={busy}
              onSelect={() => setSelected(`tool-${call.id}`)}
              onDecide={(d) => toolMut.mutate({ id: call.id, decision: d })}
              onStartRewrite={() => setRewriting(call.id)}
              onCancelRewrite={() => setRewriting(null)}
              onSendRewrite={(args) => toolMut.mutate({ id: call.id, decision: 'rewrite', final_args: args })}
            />
          ))}
        </div>
      </Panel>

      <Panel
        title={`Pending Heal Proposals (${pendingHeals.length})`}
        icon={<ShieldAlert size={18} />}
        loading={loadingHeals}
        error={errorHeals}
        empty={pendingHeals.length === 0}
        emptyTitle="No Heal Proposals"
        emptyMessage="Judge proposals for malfunctioning agent memory will appear here."
        onRetry={() => refetchHeals()}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
          {pendingHeals.map((heal) => (
            <HealCard
              key={heal.id}
              heal={heal}
              now={now}
              busy={busy}
              selected={selected === `heal-${heal.id}`}
              onSelect={() => setSelected(`heal-${heal.id}`)}
              onDecide={(d) => healMut.mutate({ id: heal.id, decision: d })}
            />
          ))}
        </div>
      </Panel>
    </div>
  );
};
