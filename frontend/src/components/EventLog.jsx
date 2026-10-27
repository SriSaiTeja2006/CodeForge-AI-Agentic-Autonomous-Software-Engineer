import React, { useState, useEffect, useRef } from 'react';
import { Terminal, ChevronRight, ChevronDown, Filter, ArrowDown } from 'lucide-react';

/**
 * EventLog displays real-time chronological execution events from the LangGraph workflow.
 */
export function EventLog({ events = [], autoScrollEnabled = true }) {
  const [expandedIds, setExpandedIds] = useState(new Set());
  const [filterQuery, setFilterQuery] = useState('');
  const [autoScroll, setAutoScroll] = useState(autoScrollEnabled);
  const terminalEndRef = useRef(null);

  useEffect(() => {
    if (autoScroll && terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events, autoScroll]);

  const toggleExpand = (id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const filteredEvents = events.filter((e) => {
    if (!filterQuery) return true;
    const q = filterQuery.toLowerCase();
    return (
      (e.message && e.message.toLowerCase().includes(q)) ||
      (e.event_type && e.event_type.toLowerCase().includes(q)) ||
      (e.stage && e.stage.toLowerCase().includes(q))
    );
  });

  if (!events || events.length === 0) {
    return (
      <div className="state-box" style={{ padding: '2rem 1rem' }}>
        <Terminal size={28} className="state-box-icon" />
        <div className="state-box-title">No execution events recorded yet</div>
        <div className="state-box-desc">
          Events will appear here as the autonomous agent executes workflow stages.
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, maxWidth: '320px' }}>
          <Filter size={14} color="var(--text-muted)" />
          <input
            type="text"
            className="form-input"
            style={{ padding: '0.35rem 0.6rem', fontSize: '0.78rem' }}
            placeholder="Filter events..."
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            type="button"
            className={`btn btn-sm ${autoScroll ? 'btn-secondary' : 'btn-ghost'}`}
            onClick={() => setAutoScroll(!autoScroll)}
            title="Toggle auto-scroll to bottom"
          >
            <ArrowDown size={13} />
            <span>Auto-scroll</span>
          </button>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            {filteredEvents.length} {filteredEvents.length === 1 ? 'event' : 'events'}
          </span>
        </div>
      </div>

      <div className="log-terminal" role="log" aria-live="polite">
        {filteredEvents.map((evt) => {
          const hasMetadata =
            evt.structured_metadata &&
            typeof evt.structured_metadata === 'object' &&
            Object.keys(evt.structured_metadata).length > 0;
          const isExpanded = expandedIds.has(evt.id);

          const timeFormatted = evt.created_at
            ? new Date(evt.created_at).toLocaleTimeString()
            : '--:--:--';

          return (
            <div key={evt.id || `${evt.stage}-${evt.created_at}`} style={{ marginBottom: '0.35rem' }}>
              <div className="log-entry">
                <span className="log-time">[{timeFormatted}]</span>
                <span className="log-stage">{evt.stage?.toUpperCase() || 'AGENT'}</span>
                <div className="log-msg">
                  <span style={{ color: 'var(--accent-blue)', fontWeight: 600, marginRight: '0.4rem' }}>
                    {evt.event_type}
                  </span>
                  <span>{evt.message}</span>
                  {hasMetadata && (
                    <button
                      type="button"
                      onClick={() => toggleExpand(evt.id)}
                      style={{
                        background: 'none',
                        border: 'none',
                        color: 'var(--accent-cyan)',
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '2px',
                        marginLeft: '0.5rem',
                        fontSize: '0.72rem',
                      }}
                    >
                      {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      <span>{isExpanded ? 'Hide info' : 'Metadata'}</span>
                    </button>
                  )}
                </div>
              </div>

              {hasMetadata && isExpanded && (
                <div
                  style={{
                    backgroundColor: 'rgba(0,0,0,0.4)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '0.5rem 0.75rem',
                    margin: '0.3rem 0 0 1.5rem',
                    fontSize: '0.75rem',
                    color: 'var(--text-secondary)',
                    overflowX: 'auto',
                  }}
                >
                  <pre style={{ margin: 0, fontFamily: 'var(--font-mono)' }}>
                    {JSON.stringify(evt.structured_metadata, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          );
        })}
        <div ref={terminalEndRef} />
      </div>
    </div>
  );
}

export default EventLog;
