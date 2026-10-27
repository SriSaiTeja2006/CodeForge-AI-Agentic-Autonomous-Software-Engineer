import React, { useState } from 'react';
import { Copy, Check, FileCode, Plus, Minus } from 'lucide-react';

/**
 * Parses and displays unified git diffs with clean syntax highlighting and line numbers.
 */
export function DiffViewer({ filePath, diffText, changeType = 'modified', summary }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    if (!diffText) return;
    navigator.clipboard.writeText(diffText).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  const lines = (diffText || '').split('\n');

  // Compute addition / deletion statistics
  let additionsCount = 0;
  let deletionsCount = 0;
  lines.forEach((line) => {
    if (line.startsWith('+') && !line.startsWith('+++')) additionsCount++;
    if (line.startsWith('-') && !line.startsWith('---')) deletionsCount++;
  });

  return (
    <div className="diff-container" style={{ marginBottom: '1.25rem' }}>
      <div className="diff-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <FileCode size={16} color="var(--accent-blue)" />
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{filePath}</span>
          <span
            className="badge badge-queued"
            style={{ textTransform: 'capitalize', fontSize: '0.68rem', padding: '0.15rem 0.4rem' }}
          >
            {changeType}
          </span>
          <div style={{ display: 'flex', gap: '0.4rem', fontSize: '0.72rem', marginLeft: '0.5rem' }}>
            <span style={{ color: 'var(--status-success)', display: 'inline-flex', alignItems: 'center', gap: '1px' }}>
              <Plus size={12} /> {additionsCount}
            </span>
            <span style={{ color: 'var(--status-error)', display: 'inline-flex', alignItems: 'center', gap: '1px' }}>
              <Minus size={12} /> {deletionsCount}
            </span>
          </div>
        </div>

        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={handleCopy}
          title="Copy diff to clipboard"
          style={{ padding: '0.2rem 0.5rem' }}
        >
          {copied ? <Check size={13} color="var(--status-success)" /> : <Copy size={13} />}
          <span>{copied ? 'Copied' : 'Copy Diff'}</span>
        </button>
      </div>

      {summary && (
        <div
          style={{
            padding: '0.5rem 1rem',
            backgroundColor: 'rgba(255, 255, 255, 0.02)',
            borderBottom: '1px solid var(--border-subtle)',
            fontSize: '0.78rem',
            color: 'var(--text-secondary)',
          }}
        >
          <strong>Summary:</strong> {summary}
        </div>
      )}

      <div style={{ overflowX: 'auto', padding: '0.5rem 0' }}>
        {lines.length === 0 || !diffText ? (
          <div style={{ padding: '1rem', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
            No diff contents recorded for this file.
          </div>
        ) : (
          lines.map((line, idx) => {
            let lineType = 'context';
            if (line.startsWith('+') && !line.startsWith('+++')) {
              lineType = 'addition';
            } else if (line.startsWith('-') && !line.startsWith('---')) {
              lineType = 'deletion';
            } else if (line.startsWith('@@')) {
              lineType = 'chunk-header';
            }

            return (
              <div key={idx} className={`diff-line ${lineType}`}>
                <span
                  style={{
                    display: 'inline-block',
                    width: '35px',
                    textAlign: 'right',
                    userSelect: 'none',
                    color: 'var(--text-dim)',
                    marginRight: '0.5rem',
                    flexShrink: 0,
                  }}
                >
                  {idx + 1}
                </span>
                <span style={{ flex: 1, wordBreak: 'break-all' }}>{line || ' '}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

export default DiffViewer;
