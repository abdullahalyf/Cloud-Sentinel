import { livePoll } from '../utils/live';
import React, { useState, useEffect, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Cpu,
  Database,
  Activity,
  ShieldAlert,
  Play,
  Pause,
  RotateCcw,
  Skull,
  DollarSign,
  CheckCircle2,
  AlertTriangle,
  History,
  Wrench,
  Sparkles,
  ArrowLeft,
  Clock,
  Layers,
  Check,
  X,
  Edit3,
} from 'lucide-react';
import { api, ApiError } from '../api/client';
import type { ToolCallRow } from '../api/types';
import { Panel } from '../components/Panel';
import { PageHeader, ago } from '../components/ui';
import { StateBadge } from '../components/StateBadge';
import { JsonEditor } from '../components/JsonEditor';
import { GraphFlow } from '../components/GraphFlow';
import { GanttReplay } from '../components/viz';
import { nodesToBars, spansToBars } from '../utils/replay';
import { DiffView } from '../components/DiffView';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { useToast } from '../components/Toast';

export const AgentDetailView: React.FC = () => {
  const { id = 'beta' } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const toast = useToast();

  // Command Bar state
  const [budgetInput, setBudgetInput] = useState<string>('');
  const [isSettingBudget, setIsSettingBudget] = useState(false);
  const [killConfirmOpen, setKillConfirmOpen] = useState(false);

  // Memory Editor state
  const [memoryText, setMemoryText] = useState<string>('{}');
  const [parsedMemory, setParsedMemory] = useState<Record<string, unknown> | null>({});
  const [isMemoryValid, setIsMemoryValid] = useState(true);
  const [memoryReason, setMemoryReason] = useState<string>('');
  const [conflictError, setConflictError] = useState<string | null>(null);
  const [conflictVersion, setConflictVersion] = useState<number | null>(null);
  const [isSavingMemory, setIsSavingMemory] = useState(false);

  // Tool Call Rewrite Modal state
  const [rewritingCall, setRewritingCall] = useState<ToolCallRow | null>(null);
  const [rewriteArgsText, setRewriteArgsText] = useState<string>('{}');
  const [parsedRewriteArgs, setParsedRewriteArgs] = useState<Record<string, unknown> | null>({});
  const [isRewriteArgsValid, setIsRewriteArgsValid] = useState(true);
  const [rewriteReason, setRewriteReason] = useState<string>('');
  const [isSubmittingRewrite, setIsSubmittingRewrite] = useState(false);

  // Query Agent Details
  const {
    data: agentData,
    isLoading: isAgentLoading,
    error: agentError,
    refetch: refetchAgent,
  } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => api.getAgent(id),
    refetchInterval: livePoll,
  });

  // Query Execution Graph Nodes
  const { data: nodesData } = useQuery({
    queryKey: ['agent-nodes', id],
    queryFn: () => api.getAgentNodes(id),
    refetchInterval: livePoll,
  });

  // Query Memory History
  const { data: historyData, refetch: refetchHistory } = useQuery({
    queryKey: ['agent-memory-history', id],
    queryFn: () => api.getMemoryHistory(id),
    refetchInterval: 2000,
  });

  // Query Tool Calls
  const { data: toolCallsData, refetch: refetchToolCalls } = useQuery({
    queryKey: ['tool-calls'],
    queryFn: () => api.getToolCalls(),
    refetchInterval: livePoll,
  });

  // Initialize Memory Editor once agent memory is loaded
  useEffect(() => {
    if (agentData?.memory?.content) {
      const formatted = JSON.stringify(agentData.memory.content, null, 2);
      setMemoryText(formatted);
      setParsedMemory(agentData.memory.content);
      setIsMemoryValid(true);
    }
  }, [agentData?.memory?.version]);

  // Initialize Budget Input once agent data is loaded
  useEffect(() => {
    if (agentData?.agent?.budget_usd !== undefined && !budgetInput) {
      setBudgetInput(agentData.agent.budget_usd.toString());
    }
  }, [agentData?.agent?.budget_usd]);

  // Filter tool calls for this agent
  const agentToolCalls = useMemo(() => {
    if (!toolCallsData?.items) return [];
    return toolCallsData.items.filter((call) => call.agent_id === id);
  }, [toolCallsData, id]);

  // Latest verdict
  const latestVerdict = useMemo(() => {
    if (agentData?.verdicts && agentData.verdicts.length > 0) {
      return agentData.verdicts[0];
    }
    return agentData?.agent?.last_verdict || null;
  }, [agentData]);

  // Spans for this agent (last 20)
  const recentSpans = useMemo(() => {
    if (!agentData?.spans || agentData.spans.length === 0) return [];
    return [...agentData.spans].slice(-20).reverse();
  }, [agentData]);

  // ─────────────────────────────────────────────────────────────────────────────
  // Command Bar Handlers
  // ─────────────────────────────────────────────────────────────────────────────
  const executeCommand = async (
    cmd: 'KILL' | 'PAUSE' | 'RESUME' | 'RESTART' | 'SET_BUDGET',
    reason: string,
    params?: Record<string, unknown>
  ) => {
    try {
      const res = await api.postCommand(id, {
        command: cmd,
        requested_by: 'dashboard',
        reason,
        params,
      });
      toast.success(
        `Command ${cmd} Dispatched`,
        `Queued command ID #${res.id} for agent ${id}`
      );
      refetchAgent();
      queryClient.invalidateQueries({ queryKey: ['fleet'] });
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.detail : 'Command failed to dispatch';
      toast.error(`Command ${cmd} Failed`, msg);
    }
  };

  const handlePause = () => executeCommand('PAUSE', 'Manual operator pause from C2 console');
  const handleResume = () => executeCommand('RESUME', 'Manual operator resume from C2 console');
  const handleRestart = () => executeCommand('RESTART', 'Manual operator restart from C2 console');

  const handleKillConfirm = (reason: string) => {
    setKillConfirmOpen(false);
    executeCommand('KILL', reason);
  };

  const handleBudgetSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const val = parseFloat(budgetInput);
    if (isNaN(val) || val < 0) {
      toast.error('Invalid Budget', 'Please enter a valid non-negative number');
      return;
    }
    setIsSettingBudget(true);
    try {
      await executeCommand('SET_BUDGET', 'Operator updated budget allocation', { budget_usd: val });
    } finally {
      setIsSettingBudget(false);
    }
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // Memory Editor Handlers
  // ─────────────────────────────────────────────────────────────────────────────
  const handleMemoryChange = (
    val: string,
    valid: boolean,
    parsed: Record<string, unknown> | null
  ) => {
    setMemoryText(val);
    setIsMemoryValid(valid);
    setParsedMemory(parsed);
  };

  const handleApplySuggestion = () => {
    if (!latestVerdict?.suggested_fix) return;
    const fixText = latestVerdict.suggested_fix;

    // Pattern: Set memory "key" to "value"
    const match = fixText.match(/Set memory ["']([^"']+)["'] to ["']([^"']+)["']/i);
    let updatedContent: Record<string, unknown> = {};

    if (match) {
      const key = match[1];
      const val = match[2];
      const baseObj = parsedMemory ? { ...parsedMemory } : {};
      baseObj[key] = val;
      updatedContent = baseObj;
    } else {
      try {
        const parsed = JSON.parse(fixText);
        updatedContent = parsed;
      } catch {
        const baseObj = parsedMemory ? { ...parsedMemory } : {};
        baseObj['fix_suggestion'] = fixText;
        updatedContent = baseObj;
      }
    }

    const formatted = JSON.stringify(updatedContent, null, 2);
    setMemoryText(formatted);
    setParsedMemory(updatedContent);
    setIsMemoryValid(true);
    setMemoryReason(`Applied verdict fix recommendation (${latestVerdict.pattern})`);
    toast.info('Suggestion Applied', 'Editor populated with recommended memory patch. Review and Save.');
  };

  const handleSaveMemory = async (forceOverwrite = false) => {
    if (!isMemoryValid || !parsedMemory) {
      toast.error('Invalid JSON', 'Cannot save malformed JSON content');
      return;
    }
    if (!memoryReason.trim()) {
      toast.error('Reason Required', 'Please provide an operator reason before saving');
      return;
    }

    setIsSavingMemory(true);
    setConflictError(null);

    const baseVersion = forceOverwrite ? null : agentData?.memory?.version ?? null;

    try {
      const res = await api.putMemory(id, {
        content: parsedMemory,
        edited_by: 'human',
        reason: memoryReason.trim(),
        base_version: baseVersion,
      });

      toast.success('Memory Persisted', `Saved v${res.version} successfully for ${id}`);
      setMemoryReason('');
      setConflictError(null);
      refetchAgent();
      refetchHistory();
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setConflictError(err.detail || 'Someone else changed the memory');
        setConflictVersion((agentData?.memory?.version ?? 1) + 1);
        toast.error('Memory Conflict (409)', err.detail || 'Memory was updated concurrently');
      } else {
        const msg = err instanceof ApiError ? err.detail : 'Failed to save memory';
        toast.error('Save Failed', msg);
      }
    } finally {
      setIsSavingMemory(false);
    }
  };

  const handleReloadMemory = async () => {
    setConflictError(null);
    try {
      const fresh = await api.getMemory(id);
      const formatted = JSON.stringify(fresh.content, null, 2);
      setMemoryText(formatted);
      setParsedMemory(fresh.content);
      setIsMemoryValid(true);
      toast.info('Memory Reloaded', `Synced with latest version (v${fresh.version})`);
      refetchAgent();
    } catch {
      toast.error('Reload Failed', 'Could not fetch fresh memory');
    }
  };

  // ─────────────────────────────────────────────────────────────────────────────
  // Tool Overrides Handlers
  // ─────────────────────────────────────────────────────────────────────────────
  const handleToolDecision = async (
    callId: number,
    decision: 'allow' | 'deny',
    toolReason: string
  ) => {
    try {
      await api.decideToolCall(callId, {
        decision,
        decided_by: 'human',
        reason: toolReason,
      });
      toast.success(
        `Tool Call ${decision.toUpperCase()}ED`,
        `Decision applied to call #${callId}`
      );
      refetchToolCalls();
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.detail : 'Decision failed';
      toast.error('Tool Decision Failed', msg);
    }
  };

  const openRewriteModal = (call: ToolCallRow) => {
    setRewritingCall(call);
    const initialArgs = JSON.stringify(call.args || {}, null, 2);
    setRewriteArgsText(initialArgs);
    setParsedRewriteArgs(call.args || {});
    setIsRewriteArgsValid(true);
    setRewriteReason('Manual operator argument rewrite');
  };

  const handleRewriteSubmit = async () => {
    if (!rewritingCall || !isRewriteArgsValid || !parsedRewriteArgs) {
      toast.error('Invalid Arguments', 'Please provide valid JSON arguments');
      return;
    }
    setIsSubmittingRewrite(true);
    try {
      await api.decideToolCall(rewritingCall.id, {
        decision: 'rewrite',
        final_args: parsedRewriteArgs,
        decided_by: 'human',
        reason: rewriteReason.trim() || 'Rewritten by operator',
      });
      toast.success(
        'Tool Call Rewritten',
        `Dispatched rewritten arguments to tool call #${rewritingCall.id}`
      );
      setRewritingCall(null);
      refetchToolCalls();
    } catch (err: unknown) {
      const msg = err instanceof ApiError ? err.detail : 'Rewrite submission failed';
      toast.error('Rewrite Failed', msg);
    } finally {
      setIsSubmittingRewrite(false);
    }
  };

  const agent = agentData?.agent;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-6)',
        width: '100%',
        animation: 'fadeIn 0.25s cubic-bezier(0, 0, 0.2, 1)',
      }}
    >
      {/* ───────────────────────────────────────────────────────────────────────────── */}
      {/* Top Header & Navigation */}
      {/* ───────────────────────────────────────────────────────────────────────────── */}
      <PageHeader
        eyebrow={
          <Link to="/fleet" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--color-text-muted)', fontWeight: 600 }}>
            <ArrowLeft size={14} /> Fleet Overview
          </Link>
        }
        title={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 14 }}>
            C2 NODE: {id}
            {agent && <StateBadge state={agent.state} />}
          </span>
        }
        summary={`Runtime ${agent?.runtime || 'unknown'} · updated ${agent?.updated_at ? ago(agent.updated_at) : 'live'} · every command here goes through the C2 API.`}
        actions={
          <button type="button" className="btn" onClick={() => refetchAgent()}>
            <Clock size={14} /> Sync
          </button>
        }
      />

      {/* ───────────────────────────────────────────────────────────────────────────── */}
      {/* Mission Control Command Bar (Top Bento Strip) */}
      {/* ───────────────────────────────────────────────────────────────────────────── */}
      <div
        data-testid="command-bar"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 'var(--space-4)',
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 'var(--radius-md)',
          padding: 'var(--space-4) var(--space-6)',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        {/* Left: Execution Control Buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
          <span
            style={{
              fontSize: 'var(--type-micro-size)',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              color: 'var(--color-text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            OPERATOR COMMANDS:
          </span>

          <button
            type="button"
            data-testid="command-pause-btn"
            onClick={handlePause}
            disabled={agent?.state === 'paused' || agentData?.agent?.state === 'killed'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: 'var(--space-2) var(--space-4)',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-state-suspicious-bg)',
              color: 'var(--color-state-suspicious)',
              border: '1px solid var(--color-state-suspicious-border)',
              fontSize: 'var(--type-body-sm-size)',
              fontWeight: 600,
              cursor: agent?.state === 'paused' || agentData?.agent?.state === 'killed' ? 'not-allowed' : 'pointer',
              opacity: agent?.state === 'paused' || agentData?.agent?.state === 'killed' ? 0.5 : 1,
            }}
          >
            <Pause size={14} /> Pause
          </button>

          <button
            type="button"
            data-testid="command-resume-btn"
            onClick={handleResume}
            disabled={agent?.state !== 'paused'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: 'var(--space-2) var(--space-4)',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-state-healthy-bg)',
              color: 'var(--color-state-healthy)',
              border: '1px solid var(--color-state-healthy-border)',
              fontSize: 'var(--type-body-sm-size)',
              fontWeight: 600,
              cursor: agent?.state !== 'paused' ? 'not-allowed' : 'pointer',
              opacity: agent?.state !== 'paused' ? 0.5 : 1,
            }}
          >
            <Play size={14} /> Resume
          </button>

          <button
            type="button"
            data-testid="command-restart-btn"
            onClick={handleRestart}
            disabled={agent?.state === 'killed'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: 'var(--space-2) var(--space-4)',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-surface-elevated)',
              color: 'var(--color-text-primary)',
              border: '1px solid var(--color-border)',
              fontSize: 'var(--type-body-sm-size)',
              fontWeight: 600,
              cursor: agent?.state === 'killed' ? 'not-allowed' : 'pointer',
              opacity: agent?.state === 'killed' ? 0.5 : 1,
            }}
          >
            <RotateCcw size={14} /> Restart
          </button>

          <button
            type="button"
            data-testid="command-kill-btn"
            onClick={() => setKillConfirmOpen(true)}
            disabled={agent?.state === 'killed'}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              padding: 'var(--space-2) var(--space-4)',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-state-killed-bg)',
              color: 'var(--color-state-killed-text)',
              border: '1px solid var(--color-state-killed-border)',
              fontSize: 'var(--type-body-sm-size)',
              fontWeight: 600,
              cursor: agent?.state === 'killed' ? 'not-allowed' : 'pointer',
              opacity: agent?.state === 'killed' ? 0.5 : 1,
            }}
          >
            <Skull size={14} /> Kill Node
          </button>
        </div>

        {/* Right: Set Budget Form */}
        <form
          onSubmit={handleBudgetSubmit}
          style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}
        >
          <span
            style={{
              fontSize: 'var(--type-micro-size)',
              fontFamily: 'var(--font-mono)',
              color: 'var(--color-text-muted)',
            }}
          >
            BUDGET ($):
          </span>
          <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
            <DollarSign
              size={14}
              style={{ position: 'absolute', left: '8px', color: 'var(--color-text-muted)' }}
            />
            <input
              type="number"
              step="0.1"
              min="0"
              data-testid="budget-input"
              value={budgetInput}
              onChange={(e) => setBudgetInput(e.target.value)}
              placeholder="0.50"
              style={{
                width: '100px',
                padding: 'var(--space-2) var(--space-3) var(--space-2) 26px',
                backgroundColor: 'var(--color-canvas)',
                border: '1px solid var(--color-border)',
                borderRadius: 'var(--radius-sm)',
                color: 'var(--color-text-primary)',
                fontFamily: 'var(--font-mono)',
                fontSize: 'var(--type-body-sm-size)',
                outline: 'none',
              }}
            />
          </div>
          <button
            type="submit"
            data-testid="budget-submit-btn"
            disabled={isSettingBudget || !budgetInput}
            style={{
              padding: 'var(--space-2) var(--space-3)',
              borderRadius: 'var(--radius-sm)',
              backgroundColor: 'var(--color-surface-elevated)',
              color: 'var(--color-telemetry-cyan)',
              border: '1px solid var(--color-border-accent)',
              fontSize: 'var(--type-micro-size)',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              cursor: isSettingBudget ? 'not-allowed' : 'pointer',
            }}
          >
            {isSettingBudget ? 'Saving...' : 'Set'}
          </button>
        </form>
      </div>

      {/* ───────────────────────────────────────────────────────────────────────────── */}
      {/* Main 12-Column Asymmetric Bento Grid */}
      {/* ───────────────────────────────────────────────────────────────────────────── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
          gap: 'var(--space-6)',
          width: '100%',
        }}
      >
        {/* ───────────────────────────────────────────────────────────────────────── */}
        {/* LEFT COLUMN: Verdicts, Tools, Spans, Nodes (col-span-7) */}
        {/* ───────────────────────────────────────────────────────────────────────── */}
        <div style={{ gridColumn: 'span 7', display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
          {/* Latest Verdict & Recommendation Panel */}
          <Panel
            title="Safety Engine Verdict"
            icon={<ShieldAlert size={18} color="var(--color-state-suspicious)" />}
            loading={isAgentLoading}
            error={agentError}
            onRetry={() => refetchAgent()}
            empty={!latestVerdict}
            emptyTitle="No Engine Verdicts"
            emptyMessage="The brain monitoring engine has not triggered any intervention verdicts for this node."
          >
            {latestVerdict && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                {/* Top strip with Action badge, confidence, pattern, and source */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: 'var(--space-2)',
                    paddingBottom: 'var(--space-3)',
                    borderBottom: '1px solid var(--color-border)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                    <span
                      style={{
                        padding: '4px 10px',
                        borderRadius: 'var(--radius-sm)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--type-body-sm-size)',
                        fontWeight: 700,
                        backgroundColor:
                          latestVerdict.action === 'KILL'
                            ? 'var(--color-state-killed-bg)'
                            : latestVerdict.action === 'PAUSE'
                            ? 'var(--color-state-suspicious-bg)'
                            : 'var(--color-state-healthy-bg)',
                        color:
                          latestVerdict.action === 'KILL'
                            ? 'var(--color-state-killed)'
                            : latestVerdict.action === 'PAUSE'
                            ? 'var(--color-state-suspicious)'
                            : 'var(--color-state-healthy)',
                        border: `1px solid ${
                          latestVerdict.action === 'KILL'
                            ? 'var(--color-state-killed-border)'
                            : latestVerdict.action === 'PAUSE'
                            ? 'var(--color-state-suspicious-border)'
                            : 'var(--color-state-healthy-border)'
                        }`,
                      }}
                    >
                      ACTION: {latestVerdict.action}
                    </span>
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--type-micro-size)',
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      PATTERN: <strong style={{ color: 'var(--color-text-primary)' }}>{latestVerdict.pattern}</strong>
                    </span>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                    <div style={{ textAlign: 'right' }}>
                      <span style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)', display: 'block' }}>
                        CONFIDENCE
                      </span>
                      <span
                        className="tabular-nums"
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 'var(--type-body-size)',
                          fontWeight: 700,
                          color: 'var(--color-telemetry-cyan)',
                        }}
                      >
                        {(latestVerdict.confidence * 100).toFixed(1)}%
                      </span>
                    </div>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: 'var(--color-surface-elevated)',
                        border: '1px solid var(--color-border)',
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--type-micro-size)',
                        color: 'var(--color-text-secondary)',
                      }}
                    >
                      JUDGE: {latestVerdict.source}
                    </span>
                  </div>
                </div>

                {/* Reason Explanation */}
                <div>
                  <div
                    style={{
                      fontSize: 'var(--type-micro-size)',
                      fontFamily: 'var(--font-mono)',
                      color: 'var(--color-text-muted)',
                      textTransform: 'uppercase',
                      marginBottom: '4px',
                    }}
                  >
                    Reasoning & Detection Evidence:
                  </div>
                  <p
                    style={{
                      fontSize: 'var(--type-body-sm-size)',
                      color: 'var(--color-text-primary)',
                      lineHeight: 1.5,
                      backgroundColor: 'var(--color-canvas)',
                      padding: 'var(--space-3)',
                      borderRadius: 'var(--radius-sm)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    {latestVerdict.reason}
                  </p>
                </div>

                {/* Suggested Fix Action */}
                {latestVerdict.suggested_fix && (
                  <div
                    data-testid="suggested-fix-banner"
                    style={{
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 'var(--space-2)',
                      padding: 'var(--space-3) var(--space-4)',
                      borderRadius: 'var(--radius-sm)',
                      backgroundColor: 'var(--color-state-probation-bg)',
                      border: '1px solid var(--color-border-accent)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          color: 'var(--color-telemetry-cyan)',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 'var(--type-micro-size)',
                          fontWeight: 700,
                        }}
                      >
                        <Sparkles size={14} /> AUTONOMOUS HEAL RECOMMENDATION:
                      </div>
                      <button
                        type="button"
                        data-testid="apply-suggestion-btn"
                        onClick={handleApplySuggestion}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '4px',
                          padding: '4px 10px',
                          borderRadius: 'var(--radius-sm)',
                          backgroundColor: 'var(--color-accent)',
                          color: 'var(--color-canvas)',
                          border: 'none',
                          fontSize: 'var(--type-micro-size)',
                          fontFamily: 'var(--font-mono)',
                          fontWeight: 700,
                        }}
                      >
                        Apply suggestion
                      </button>
                    </div>
                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 'var(--type-micro-size)',
                        color: 'var(--color-text-primary)',
                        lineHeight: 1.4,
                      }}
                    >
                      {latestVerdict.suggested_fix}
                    </div>
                  </div>
                )}
              </div>
            )}
          </Panel>

          {/* Tool Calls & Operator Overrides */}
          <Panel
            title={`Tool Overrides & Interventions (${agentToolCalls.length})`}
            icon={<Wrench size={18} />}
            empty={agentToolCalls.length === 0}
            emptyTitle="No Tool Calls"
            emptyMessage="No tool calls recorded for this agent yet. Tools requiring approval will appear here."
          >
            {agentToolCalls.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                {agentToolCalls.map((call) => {
                  const isPending = call.decision === 'pending';
                  return (
                    <div
                      key={call.id}
                      data-testid={`tool-call-${call.id}`}
                      style={{
                        backgroundColor: 'var(--color-canvas)',
                        border: `1px solid ${
                          isPending ? 'var(--color-border-accent)' : 'var(--color-border)'
                        }`,
                        borderRadius: 'var(--radius-sm)',
                        padding: 'var(--space-3)',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: 'var(--space-2)',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          flexWrap: 'wrap',
                          gap: 'var(--space-2)',
                        }}
                      >
                        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                          <span
                            style={{
                              fontFamily: 'var(--font-mono)',
                              fontSize: 'var(--type-body-sm-size)',
                              fontWeight: 700,
                              color: 'var(--color-text-primary)',
                            }}
                          >
                            {call.tool_name}
                          </span>
                          <span
                            style={{
                              padding: '2px 6px',
                              borderRadius: 'var(--radius-sm)',
                              fontFamily: 'var(--font-mono)',
                              fontSize: 'var(--type-micro-size)',
                              fontWeight: 600,
                              backgroundColor:
                                call.decision === 'allow'
                                  ? 'var(--color-state-healthy-bg)'
                                  : call.decision === 'deny'
                                  ? 'var(--color-state-killed-bg)'
                                  : call.decision === 'rewrite'
                                  ? 'var(--color-state-suspicious-bg)'
                                  : 'var(--color-state-probation-bg)',
                              color:
                                call.decision === 'allow'
                                  ? 'var(--color-state-healthy)'
                                  : call.decision === 'deny'
                                  ? 'var(--color-state-killed)'
                                  : call.decision === 'rewrite'
                                  ? 'var(--color-state-suspicious)'
                                  : 'var(--color-telemetry-cyan)',
                            }}
                          >
                            {call.decision.toUpperCase()}
                          </span>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                          <span
                            className="tabular-nums"
                            style={{
                              fontFamily: 'var(--font-mono)',
                              fontSize: 'var(--type-micro-size)',
                              color: 'var(--color-text-muted)',
                            }}
                          >
                            {call.value_usd ? `$${call.value_usd.toFixed(2)}` : 'FREE'}
                          </span>
                          <span
                            style={{
                              fontFamily: 'var(--font-mono)',
                              fontSize: 'var(--type-micro-size)',
                              color: 'var(--color-text-muted)',
                            }}
                          >
                            ID: #{call.id}
                          </span>
                        </div>
                      </div>

                      {/* Args Preview */}
                      <pre
                        style={{
                          margin: 0,
                          padding: 'var(--space-2)',
                          backgroundColor: 'var(--color-surface)',
                          borderRadius: 'var(--radius-sm)',
                          fontFamily: 'var(--font-mono)',
                          fontSize: 'var(--type-micro-size)',
                          color: 'var(--color-text-secondary)',
                          overflowX: 'auto',
                          maxHeight: '120px',
                        }}
                      >
                        {JSON.stringify(call.args, null, 2)}
                      </pre>

                      {call.reason && (
                        <div
                          style={{
                            fontSize: 'var(--type-micro-size)',
                            color: 'var(--color-text-muted)',
                            fontStyle: 'italic',
                          }}
                        >
                          Policy: {call.reason}
                        </div>
                      )}

                      {/* Pending Action Buttons */}
                      {isPending && (
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'flex-end',
                            gap: 'var(--space-2)',
                            // The panel clips its overflow, so the buttons must wrap
                            // rather than be squeezed out of the card and become
                            // unclickable.
                            flexWrap: 'wrap',
                            marginTop: 'var(--space-1)',
                            borderTop: '1px solid var(--color-border)',
                            paddingTop: 'var(--space-2)',
                          }}
                        >
                          <button
                            type="button"
                            data-testid="tool-approve-btn"
                            onClick={() =>
                              handleToolDecision(call.id, 'allow', 'Operator manual approval')
                            }
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '4px 10px',
                              borderRadius: 'var(--radius-sm)',
                              backgroundColor: 'var(--color-state-healthy-bg)',
                              color: 'var(--color-state-healthy)',
                              border: '1px solid var(--color-state-healthy-border)',
                              fontSize: 'var(--type-micro-size)',
                              fontWeight: 600,
                            }}
                          >
                            <Check size={12} /> Approve
                          </button>
                          <button
                            type="button"
                            data-testid="tool-deny-btn"
                            onClick={() =>
                              handleToolDecision(call.id, 'deny', 'Operator manual denial')
                            }
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '4px 10px',
                              borderRadius: 'var(--radius-sm)',
                              backgroundColor: 'var(--color-state-killed-bg)',
                              color: 'var(--color-state-killed)',
                              border: '1px solid var(--color-state-killed-border)',
                              fontSize: 'var(--type-micro-size)',
                              fontWeight: 600,
                            }}
                          >
                            <X size={12} /> Deny
                          </button>
                          <button
                            type="button"
                            data-testid="tool-rewrite-btn"
                            onClick={() => openRewriteModal(call)}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              padding: '4px 10px',
                              borderRadius: 'var(--radius-sm)',
                              backgroundColor: 'var(--color-surface-elevated)',
                              color: 'var(--color-telemetry-cyan)',
                              border: '1px solid var(--color-border-accent)',
                              fontSize: 'var(--type-micro-size)',
                              fontWeight: 600,
                            }}
                          >
                            <Edit3 size={12} /> Rewrite
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Panel>

          {/* Execution Spans DataTable (Last 20) */}
          {(() => {
            const bars = [...spansToBars(recentSpans), ...nodesToBars(nodesData?.items ?? [])];
            return bars.length > 0 ? (
              <section className="card" aria-label="Session replay" style={{ padding: 'var(--space-5) var(--space-6)' }}>
                <GanttReplay bars={bars} title="Session replay" testId="session-replay" />
              </section>
            ) : null;
          })()}

          <Panel
            title={`Execution Trace Spans (${recentSpans.length})`}
            icon={<Layers size={18} />}
            empty={recentSpans.length === 0}
            emptyTitle="No Execution Spans Recorded"
            emptyMessage="Agent has not emitted OpenTelemetry spans in this active run window."
          >
            {recentSpans.length > 0 && (
              <div style={{ overflowX: 'auto' }}>
                <table
                  data-testid="spans-table"
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    textAlign: 'left',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 'var(--type-micro-size)',
                  }}
                >
                  <thead>
                    <tr
                      style={{
                        borderBottom: '1px solid var(--color-border)',
                        color: 'var(--color-text-muted)',
                      }}
                    >
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>OPERATION</th>
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>STATUS</th>
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>DURATION</th>
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>TOKENS / COST</th>
                      <th style={{ padding: 'var(--space-2) var(--space-3)' }}>ATTRIBUTES</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentSpans.map((span, idx) => (
                      <tr
                        key={span.span_id || idx}
                        style={{
                          borderBottom: '1px solid var(--color-border)',
                          backgroundColor: idx % 2 === 0 ? 'transparent' : 'var(--color-fill)',
                        }}
                      >
                        <td style={{ padding: 'var(--space-2) var(--space-3)', color: 'var(--color-text-primary)' }}>
                          {span.name || span.operation}
                        </td>
                        <td style={{ padding: 'var(--space-2) var(--space-3)' }}>
                          <span
                            style={{
                              color:
                                span.status === 'error'
                                  ? 'var(--color-state-killed)'
                                  : 'var(--color-state-healthy)',
                              fontWeight: 600,
                            }}
                          >
                            {(span.status || 'OK').toUpperCase()}
                          </span>
                        </td>
                        <td className="tabular-nums" style={{ padding: 'var(--space-2) var(--space-3)', color: 'var(--color-text-secondary)' }}>
                          {span.duration_ms ? `${span.duration_ms.toFixed(1)} ms` : '—'}
                        </td>
                        <td className="tabular-nums" style={{ padding: 'var(--space-2) var(--space-3)', color: 'var(--color-telemetry-cyan)' }}>
                          {span.cost_usd ? `$${span.cost_usd.toFixed(4)}` : '—'}
                        </td>
                        <td
                          style={{
                            padding: 'var(--space-2) var(--space-3)',
                            color: 'var(--color-text-muted)',
                            maxWidth: '240px',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                          }}
                        >
                          {typeof span.tool_args === 'object'
                            ? JSON.stringify(span.tool_args)
                            : span.prompt_preview || '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          {/* Graph flow panel (D6) */}
          <Panel
            title="Graph flow"
            icon={<Activity size={18} />}
            empty={!nodesData || nodesData.items.length === 0}
            emptyTitle="No Execution Graph Recorded"
            emptyMessage="Agent has not emitted graph_node spans yet. Connect the cloudsentinel SDK adapter."
          >
            {nodesData && nodesData.items.length > 0 && (
              <GraphFlow feed={nodesData} paused={agentData?.agent?.state === 'paused' || agentData?.agent?.state === 'killed'} />
            )}
          </Panel>
        </div>

        {/* ───────────────────────────────────────────────────────────────────────── */}
        {/* RIGHT COLUMN: Telemetry Overview, Memory Editor & History (col-span-5) */}
        {/* ───────────────────────────────────────────────────────────────────────── */}
        <div style={{ gridColumn: 'span 5', display: 'flex', flexDirection: 'column', gap: 'var(--space-6)' }}>
          {/* Node Telemetry Quick Card */}
          <Panel title={`Node Telemetry: ${id}`} icon={<Cpu size={18} />}>
            {agent && (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-4)' }}>
                <div>
                  <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>
                    CURRENT STATE
                  </div>
                  <div style={{ fontSize: 'var(--type-body-size)', fontWeight: 700, marginTop: '2px' }}>
                    <StateBadge state={agent.state} />
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>
                    BURN RATE
                  </div>
                  <div
                    className="tabular-nums"
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--type-body-size)',
                      fontWeight: 700,
                      marginTop: '2px',
                      color: agent.usd_per_min > 0.1 ? 'var(--color-state-suspicious)' : 'var(--color-text-primary)',
                    }}
                  >
                    ${agent.usd_per_min.toFixed(4)}/min
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>
                    SPEND / BUDGET
                  </div>
                  <div
                    className="tabular-nums"
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--type-body-size)',
                      fontWeight: 700,
                      marginTop: '2px',
                    }}
                  >
                    ${agent.spend_usd.toFixed(2)} / ${agent.budget_usd.toFixed(2)}
                  </div>
                </div>

                <div>
                  <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-muted)' }}>
                    LOOP SCORE
                  </div>
                  <div
                    className="tabular-nums"
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--type-body-size)',
                      fontWeight: 700,
                      marginTop: '2px',
                      color: agent.loop_score > 0.5 ? 'var(--color-state-killed)' : 'var(--color-state-healthy)',
                    }}
                  >
                    {agent.loop_score.toFixed(2)}
                  </div>
                </div>
              </div>
            )}
          </Panel>

          {/* Working Memory Editor with Validation, Diff, and Conflict Handling */}
          <Panel
            title={`Working Memory Editor (v${agentData?.memory?.version ?? 1})`}
            icon={<Database size={18} color="var(--color-telemetry-cyan)" />}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
              {/* 409 Conflict Banner */}
              {conflictError && (
                <div
                  data-testid="memory-conflict-banner"
                  style={{
                    backgroundColor: 'var(--color-state-killed-bg)',
                    border: '1px solid var(--color-state-killed-border)',
                    borderRadius: 'var(--radius-sm)',
                    padding: 'var(--space-3)',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 'var(--space-2)',
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 'var(--space-2)',
                      color: 'var(--color-state-killed)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--type-micro-size)',
                      fontWeight: 700,
                    }}
                  >
                    <AlertTriangle size={16} />
                    <span>Someone else changed the memory (version {conflictVersion || 'newer'})</span>
                  </div>
                  <div style={{ fontSize: 'var(--type-micro-size)', color: 'var(--color-text-secondary)' }}>
                    {conflictError}
                  </div>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-1)' }}>
                    <button
                      type="button"
                      data-testid="conflict-reload-btn"
                      onClick={handleReloadMemory}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: 'var(--color-surface-elevated)',
                        color: 'var(--color-text-primary)',
                        border: '1px solid var(--color-border)',
                        fontSize: 'var(--type-micro-size)',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      Reload
                    </button>
                    <button
                      type="button"
                      data-testid="conflict-overwrite-btn"
                      onClick={() => handleSaveMemory(true)}
                      style={{
                        padding: '4px 10px',
                        borderRadius: 'var(--radius-sm)',
                        backgroundColor: 'var(--color-state-killed)',
                        color: '#fff',
                        border: 'none',
                        fontSize: 'var(--type-micro-size)',
                        fontFamily: 'var(--font-mono)',
                        fontWeight: 600,
                      }}
                    >
                      Overwrite
                    </button>
                  </div>
                </div>
              )}

              {/* Json Editor Textarea with validation */}
              <JsonEditor
                value={memoryText}
                onChange={handleMemoryChange}
                minHeight="220px"
                dataTestId="memory-json-editor"
              />

              {/* Diff View against Saved Baseline */}
              <div>
                <DiffView
                  saved={agentData?.memory?.content || null}
                  current={parsedMemory}
                  savedVersion={agentData?.memory?.version}
                />
              </div>

              {/* Operator Reason Input (Mandatory) */}
              <div>
                <label
                  htmlFor="memory-reason"
                  style={{
                    display: 'block',
                    fontSize: 'var(--type-micro-size)',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--color-text-muted)',
                    textTransform: 'uppercase',
                    marginBottom: 'var(--space-1)',
                  }}
                >
                  Operator Reason (Required for Audit Trail):
                </label>
                <input
                  id="memory-reason"
                  type="text"
                  data-testid="memory-reason-input"
                  value={memoryReason}
                  onChange={(e) => setMemoryReason(e.target.value)}
                  placeholder="e.g. Cleared stuck order retry loop from memory"
                  style={{
                    width: '100%',
                    padding: 'var(--space-2) var(--space-3)',
                    backgroundColor: 'var(--color-canvas)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--color-text-primary)',
                    fontFamily: 'var(--font-sans)',
                    fontSize: 'var(--type-body-sm-size)',
                    outline: 'none',
                  }}
                />
              </div>

              {/* Save Memory Button */}
              <button
                type="button"
                data-testid="memory-save-btn"
                disabled={!isMemoryValid || !memoryReason.trim() || isSavingMemory}
                onClick={() => handleSaveMemory(false)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  gap: 'var(--space-2)',
                  padding: 'var(--space-3) var(--space-4)',
                  borderRadius: 'var(--radius-sm)',
                  backgroundColor: 'var(--color-accent)',
                  color: '#fff',
                  border: 'none',
                  fontSize: 'var(--type-body-sm-size)',
                  fontWeight: 600,
                  cursor: !isMemoryValid || !memoryReason.trim() || isSavingMemory ? 'not-allowed' : 'pointer',
                  opacity: !isMemoryValid || !memoryReason.trim() || isSavingMemory ? 0.5 : 1,
                  transition: 'opacity var(--transition-fast)',
                }}
              >
                <CheckCircle2 size={16} />
                <span>{isSavingMemory ? 'Persisting...' : 'Save Memory Changes'}</span>
              </button>
            </div>
          </Panel>

          {/* Memory Version History */}
          <Panel
            title="Memory Version History"
            icon={<History size={18} />}
            empty={!historyData || historyData.items.length === 0}
            emptyTitle="No Memory Versions"
            emptyMessage="No previous memory revisions recorded for this agent."
          >
            {historyData && historyData.items.length > 0 && (
              <div
                data-testid="memory-history-list"
                tabIndex={0}
                aria-label="Memory version history"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 'var(--space-2)',
                  maxHeight: '260px',
                  overflowY: 'auto',
                }}
              >
                {historyData.items.map((item) => (
                  <div
                    key={item.version}
                    data-testid={`memory-history-v${item.version}`}
                    style={{
                      backgroundColor: 'var(--color-canvas)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 'var(--radius-sm)',
                      padding: 'var(--space-2) var(--space-3)',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 'var(--type-micro-size)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 700, color: 'var(--color-telemetry-cyan)' }}>
                        v{item.version}
                      </span>
                      <span style={{ color: 'var(--color-text-muted)' }}>
                        by {item.edited_by.toUpperCase()} · {item.created_at}
                      </span>
                    </div>
                    {item.reason && (
                      <div style={{ color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                        Reason: {item.reason}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>

      {/* ───────────────────────────────────────────────────────────────────────────── */}
      {/* Danger Confirmation Modal for KILL */}
      {/* ───────────────────────────────────────────────────────────────────────────── */}
      <ConfirmDialog
        isOpen={killConfirmOpen}
        title="Confirm Kill Action"
        message="Terminating this agent immediately cancels all running tasks, denies tool executions, and halts container processes."
        agentId={id}
        confirmLabel="Terminate Node (KILL)"
        isDangerous={true}
        onConfirm={handleKillConfirm}
        onCancel={() => setKillConfirmOpen(false)}
      />

      {/* ───────────────────────────────────────────────────────────────────────────── */}
      {/* Tool Call Rewrite Dialog Modal */}
      {/* ───────────────────────────────────────────────────────────────────────────── */}
      {rewritingCall && (
        <div
          role="dialog"
          aria-modal="true"
          data-testid="rewrite-dialog"
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(25, 18, 34, 0.38)',
            zIndex: 99999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 'var(--space-4)',
          }}
        >
          <div
            style={{
              width: '100%',
              maxWidth: '560px',
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 'var(--radius-md)',
              boxShadow: 'var(--shadow-pop)',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              animation: 'modalIn 0.18s cubic-bezier(0, 0, 0.2, 1)',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: 'var(--space-4) var(--space-6)',
                borderBottom: '1px solid var(--color-border)',
                backgroundColor: 'var(--color-surface-elevated)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                <Edit3 size={18} color="var(--color-telemetry-cyan)" />
                <h2
                  style={{
                    fontSize: 'var(--type-body-size)',
                    fontWeight: 700,
                    color: 'var(--color-text-primary)',
                  }}
                >
                  Rewrite Tool Call: {rewritingCall.tool_name}
                </h2>
              </div>
              <button
                type="button"
                data-testid="rewrite-cancel-btn"
                onClick={() => setRewritingCall(null)}
                style={{
                  color: 'var(--color-text-muted)',
                  padding: '4px',
                  background: 'none',
                  border: 'none',
                }}
              >
                <X size={16} />
              </button>
            </div>

            <div
              style={{
                padding: 'var(--space-6)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-4)',
              }}
            >
              <div>
                <label
                  style={{
                    display: 'block',
                    fontSize: 'var(--type-micro-size)',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--color-text-muted)',
                    textTransform: 'uppercase',
                    marginBottom: 'var(--space-1)',
                  }}
                >
                  Final Arguments (JSON Object):
                </label>
                <JsonEditor
                  value={rewriteArgsText}
                  onChange={(val, valid, parsed) => {
                    setRewriteArgsText(val);
                    setIsRewriteArgsValid(valid);
                    setParsedRewriteArgs(parsed);
                  }}
                  minHeight="160px"
                  dataTestId="rewrite-json-editor"
                />
              </div>

              <div>
                <label
                  htmlFor="rewrite-reason"
                  style={{
                    display: 'block',
                    fontSize: 'var(--type-micro-size)',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--color-text-muted)',
                    textTransform: 'uppercase',
                    marginBottom: 'var(--space-1)',
                  }}
                >
                  Rewrite Reason:
                </label>
                <input
                  id="rewrite-reason"
                  type="text"
                  data-testid="rewrite-reason-input"
                  value={rewriteReason}
                  onChange={(e) => setRewriteReason(e.target.value)}
                  placeholder="Reason for modifying arguments"
                  style={{
                    width: '100%',
                    padding: 'var(--space-2) var(--space-3)',
                    backgroundColor: 'var(--color-canvas)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--color-text-primary)',
                    fontFamily: 'var(--font-sans)',
                    fontSize: 'var(--type-body-sm-size)',
                    outline: 'none',
                  }}
                />
              </div>

              <div
                style={{
                  display: 'flex',
                  justifyContent: 'flex-end',
                  gap: 'var(--space-3)',
                  marginTop: 'var(--space-2)',
                }}
              >
                <button
                  type="button"
                  onClick={() => setRewritingCall(null)}
                  style={{
                    padding: 'var(--space-2) var(--space-4)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: 'var(--type-body-sm-size)',
                    fontWeight: 600,
                    backgroundColor: 'var(--color-surface-elevated)',
                    color: 'var(--color-text-secondary)',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  data-testid="rewrite-submit-btn"
                  disabled={!isRewriteArgsValid || isSubmittingRewrite}
                  onClick={handleRewriteSubmit}
                  style={{
                    padding: 'var(--space-2) var(--space-4)',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: 'var(--type-body-sm-size)',
                    fontWeight: 600,
                    backgroundColor: 'var(--color-accent)',
                    color: '#fff',
                    border: 'none',
                    cursor: isRewriteArgsValid && !isSubmittingRewrite ? 'pointer' : 'not-allowed',
                    opacity: isRewriteArgsValid && !isSubmittingRewrite ? 1 : 0.5,
                  }}
                >
                  {isSubmittingRewrite ? 'Dispatching...' : 'Submit Rewrite'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
export default AgentDetailView;
