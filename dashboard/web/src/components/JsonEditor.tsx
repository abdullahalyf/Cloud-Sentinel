import React, { useState, useEffect, useMemo } from 'react';
import { AlertCircle, CheckCircle2, Sparkles } from 'lucide-react';

interface JsonEditorProps {
  value: string;
  onChange: (value: string, isValid: boolean, parsed: Record<string, unknown> | null) => void;
  readOnly?: boolean;
  minHeight?: string;
  dataTestId?: string;
}

export const JsonEditor: React.FC<JsonEditorProps> = ({
  value,
  onChange,
  readOnly = false,
  minHeight = '240px',
  dataTestId = 'json-editor',
}) => {
  const [text, setText] = useState(value);
  const [error, setError] = useState<string | null>(null);

  // Sync internal state when prop changes from outside (e.g. Apply suggestion)
  useEffect(() => {
    setText(value);
    validateJson(value);
  }, [value]);

  const validateJson = (val: string) => {
    if (!val.trim()) {
      setError(null);
      onChange(val, true, {});
      return;
    }
    try {
      const parsed = JSON.parse(val);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setError('Root JSON value must be an object (e.g. {"key": "value"})');
        onChange(val, false, null);
        return;
      }
      setError(null);
      onChange(val, true, parsed);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Invalid JSON syntax';
      setError(msg);
      onChange(val, false, null);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newVal = e.target.value;
    setText(newVal);
    validateJson(newVal);
  };

  const handleFormat = () => {
    try {
      const parsed = JSON.parse(text);
      const formatted = JSON.stringify(parsed, null, 2);
      setText(formatted);
      validateJson(formatted);
    } catch {
      // Cannot format invalid JSON
    }
  };

  const linesCount = useMemo(() => {
    return Math.max(1, text.split('\n').length);
  }, [text]);

  return (
    <div
      data-testid={dataTestId}
      style={{
        display: 'flex',
        flexDirection: 'column',
        borderRadius: 'var(--radius-sm)',
        border: `1px solid ${error ? 'var(--color-state-killed-border)' : 'var(--color-border)'}`,
        backgroundColor: 'var(--color-canvas)',
        overflow: 'hidden',
      }}
    >
      {/* Editor Toolbar */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: 'var(--space-2) var(--space-3)',
          backgroundColor: 'var(--color-surface-elevated)',
          borderBottom: '1px solid var(--color-border)',
          fontSize: 'var(--type-micro-size)',
          fontFamily: 'var(--font-mono)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          {error ? (
            <span
              style={{
                color: 'var(--color-state-killed)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                fontWeight: 600,
              }}
            >
              <AlertCircle size={14} /> INVALID JSON
            </span>
          ) : (
            <span
              style={{
                color: 'var(--color-state-healthy)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                fontWeight: 600,
              }}
            >
              <CheckCircle2 size={14} /> VALID JSON
            </span>
          )}
          <span style={{ color: 'var(--color-text-muted)' }}>({linesCount} lines)</span>
        </div>

        {!readOnly && (
          <button
            type="button"
            data-testid="format-json-btn"
            onClick={handleFormat}
            disabled={!!error}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
              padding: '2px 8px',
              borderRadius: 'var(--radius-sm)',
              fontSize: 'var(--type-micro-size)',
              fontFamily: 'var(--font-mono)',
              backgroundColor: 'var(--color-surface)',
              color: error ? 'var(--color-text-muted)' : 'var(--color-telemetry-cyan)',
              border: '1px solid var(--color-border)',
              cursor: error ? 'not-allowed' : 'pointer',
              opacity: error ? 0.5 : 1,
            }}
          >
            <Sparkles size={12} /> Format
          </button>
        )}
      </div>

      {/* Editor Body with Line Numbers */}
      <div style={{ display: 'flex', minHeight, position: 'relative' }}>
        {/* Line Numbers Gutter */}
        <div
          aria-hidden="true"
          style={{
            userSelect: 'none',
            padding: 'var(--space-3) var(--space-2)',
            backgroundColor: 'rgba(14, 19, 31, 0.65)',
            borderRight: '1px solid var(--color-border)',
            color: 'var(--color-text-muted)',
            fontFamily: 'var(--font-mono)',
            fontSize: 'var(--type-micro-size)',
            lineHeight: '1.5',
            textAlign: 'right',
            minWidth: '40px',
            opacity: 0.6,
          }}
        >
          {Array.from({ length: linesCount }, (_, i) => (
            <div key={i + 1}>{i + 1}</div>
          ))}
        </div>

        {/* Textarea */}
        <textarea
          data-testid="json-editor-textarea"
          value={text}
          onChange={handleChange}
          readOnly={readOnly}
          spellCheck={false}
          style={{
            flex: 1,
            backgroundColor: 'transparent',
            color: 'var(--color-text-primary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 'var(--type-body-sm-size)',
            lineHeight: '1.5',
            padding: 'var(--space-3)',
            border: 'none',
            outline: 'none',
            resize: 'vertical',
            width: '100%',
            whiteSpace: 'pre',
            tabSize: 2,
          }}
        />
      </div>

      {/* Inline Parse Error Banner */}
      {error && (
        <div
          role="alert"
          data-testid="json-editor-error"
          style={{
            padding: 'var(--space-2) var(--space-3)',
            backgroundColor: 'var(--color-state-killed-bg)',
            borderTop: '1px solid var(--color-state-killed-border)',
            color: 'var(--color-state-killed)',
            fontSize: 'var(--type-micro-size)',
            fontFamily: 'var(--font-mono)',
            display: 'flex',
            alignItems: 'center',
            gap: 'var(--space-2)',
          }}
        >
          <AlertCircle size={14} style={{ flexShrink: 0 }} />
          <span>{error}</span>
        </div>
      )}
    </div>
  );
};

