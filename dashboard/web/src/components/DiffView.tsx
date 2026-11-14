import React, { useMemo } from 'react';
import { Plus, Minus, RefreshCw, Check } from 'lucide-react';

interface DiffViewProps {
  saved: Record<string, unknown> | null;
  current: Record<string, unknown> | null;
  savedVersion?: number;
}

interface DiffEntry {
  type: 'added' | 'removed' | 'modified' | 'unchanged';
  key: string;
  oldValue?: string;
  newValue?: string;
}

export const DiffView: React.FC<DiffViewProps> = ({ saved, current, savedVersion }) => {
  const diffs = useMemo<DiffEntry[]>(() => {
    if (!current) return [];

    const savedObj = saved || {};
    const allKeys = Array.from(new Set([...Object.keys(savedObj), ...Object.keys(current)])).sort();
    const result: DiffEntry[] = [];

    for (const key of allKeys) {
      const hasOld = key in savedObj;
      const hasNew = key in current;

      if (!hasOld && hasNew) {
        result.push({
          type: 'added',
          key,
          newValue: JSON.stringify(current[key], null, 2),
        });
      } else if (hasOld && !hasNew) {
        result.push({
          type: 'removed',
          key,
          oldValue: JSON.stringify(savedObj[key], null, 2),
        });
      } else {
        const oldStr = JSON.stringify(savedObj[key]);
        const newStr = JSON.stringify(current[key]);
        if (oldStr !== newStr) {
          result.push({
            type: 'modified',
            key,
            oldValue: JSON.stringify(savedObj[key], null, 2),
            newValue: JSON.stringify(current[key], null, 2),
          });
        }
      }
    }

    return result;
  }, [saved, current]);

  if (!current) {
    return (
      <div
        data-testid="diff-view-invalid"
        style={{
          padding: 'var(--space-3)',
          backgroundColor: 'var(--color-surface)',
          borderRadius: 'var(--radius-sm)',
          border: '1px dashed var(--color-border)',
          fontFamily: 'var(--font-code)',
          fontSize: 'var(--type-micro-size)',
          color: 'var(--color-text-muted)',
          textAlign: 'center',
        }}
      >
        Resolve JSON syntax errors in editor to preview diff against saved version
      </div>
    );
  }

  if (diffs.length === 0) {
    return (
      <div
        data-testid="diff-view-clean"
        style={{
          padding: 'var(--space-3) var(--space-4)',
          backgroundColor: 'var(--color-state-healthy-bg)',
          borderRadius: 'var(--radius-sm)',
          border: '1px solid var(--color-state-healthy-border)',
          fontFamily: 'var(--font-code)',
          fontSize: 'var(--type-micro-size)',
          color: 'var(--color-state-healthy)',
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-2)',
        }}
      >
        <Check size={14} />
        <span>No unsaved changes (matches v{savedVersion ?? 1} baseline)</span>
      </div>
    );
  }

  return (
    <div
      data-testid="diff-view-content"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-2)',
        backgroundColor: 'var(--color-surface-elevated)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-sm)',
        padding: 'var(--space-3)',
        maxHeight: '260px',
        overflowY: 'auto',
      }}
    >
      <div
        style={{
          fontSize: 'var(--type-micro-size)',
          fontFamily: 'var(--font-code)',
          color: 'var(--color-text-muted)',
          display: 'flex',
          justifyContent: 'space-between',
          borderBottom: '1px solid var(--color-border)',
          paddingBottom: 'var(--space-1)',
          marginBottom: 'var(--space-1)',
        }}
      >
        <span>CHANGES AGAINST SAVED (v{savedVersion ?? 1})</span>
        <span style={{ color: 'var(--color-telemetry-cyan)' }}>
          {diffs.length} key{diffs.length === 1 ? '' : 's'} changed
        </span>
      </div>

      {diffs.map((diff) => {
        if (diff.type === 'added') {
          return (
            <div
              key={diff.key}
              data-testid={`diff-added-${diff.key}`}
              style={{
                backgroundColor: 'var(--color-state-healthy-bg)',
                border: '1px solid var(--color-state-healthy-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-2) var(--space-3)',
                fontFamily: 'var(--font-code)',
                fontSize: 'var(--type-micro-size)',
              }}
            >
              <div style={{ color: 'var(--color-state-healthy)', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
                <Plus size={12} /> ADD KEY: &quot;{diff.key}&quot;
              </div>
              <pre style={{ margin: '4px 0 0 0', color: 'var(--color-text-primary)', whiteSpace: 'pre-wrap' }}>
                {diff.newValue}
              </pre>
            </div>
          );
        }

        if (diff.type === 'removed') {
          return (
            <div
              key={diff.key}
              data-testid={`diff-removed-${diff.key}`}
              style={{
                backgroundColor: 'var(--color-state-killed-bg)',
                border: '1px solid var(--color-state-killed-border)',
                borderRadius: 'var(--radius-sm)',
                padding: 'var(--space-2) var(--space-3)',
                fontFamily: 'var(--font-code)',
                fontSize: 'var(--type-micro-size)',
              }}
            >
              <div style={{ color: 'var(--color-state-killed)', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
                <Minus size={12} /> REMOVE KEY: &quot;{diff.key}&quot;
              </div>
              <pre style={{ margin: '4px 0 0 0', color: 'var(--color-text-muted)', textDecoration: 'line-through', whiteSpace: 'pre-wrap' }}>
                {diff.oldValue}
              </pre>
            </div>
          );
        }

        return (
          <div
            key={diff.key}
            data-testid={`diff-modified-${diff.key}`}
            style={{
              backgroundColor: 'var(--color-state-suspicious-bg)',
              border: '1px solid var(--color-state-suspicious-border)',
              borderRadius: 'var(--radius-sm)',
              padding: 'var(--space-2) var(--space-3)',
              fontFamily: 'var(--font-code)',
              fontSize: 'var(--type-micro-size)',
            }}
          >
            <div style={{ color: 'var(--color-state-suspicious)', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
              <RefreshCw size={12} /> MODIFY KEY: &quot;{diff.key}&quot;
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-2)', marginTop: '4px' }}>
              <div>
                <span style={{ color: 'var(--color-text-muted)', fontSize: '10px' }}>OLD VALUE:</span>
                <pre style={{ margin: '2px 0 0 0', color: 'var(--color-text-secondary)', whiteSpace: 'pre-wrap' }}>
                  {diff.oldValue}
                </pre>
              </div>
              <div>
                <span style={{ color: 'var(--color-state-healthy)', fontSize: '10px' }}>NEW VALUE:</span>
                <pre style={{ margin: '2px 0 0 0', color: 'var(--color-text-primary)', whiteSpace: 'pre-wrap' }}>
                  {diff.newValue}
                </pre>
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};

