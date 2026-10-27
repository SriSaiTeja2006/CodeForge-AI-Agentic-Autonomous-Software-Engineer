import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  CheckSquare,
  CheckCircle2,
  XCircle,
  Clock,
  Terminal,
  AlertTriangle,
  ArrowLeft,
  RefreshCw,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { api, getErrorMessage } from '../api/client';

export function TestResults() {
  const { taskId } = useParams();
  const [tasksList, setTasksList] = useState([]);
  const [selectedId, setSelectedId] = useState(taskId || null);
  const [tests, setTests] = useState([]);
  const [taskState, setTaskState] = useState(null);
  const [tasksLoading, setTasksLoading] = useState(!taskId);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState(null);
  const [expandedRunIds, setExpandedRunIds] = useState(new Set());

  const loadTasks = useCallback(async () => {
    setTasksLoading(true);
    try {
      const res = await api.listTasks({ page: 1, pageSize: 25 });
      const items = res?.items || [];
      setTasksList(items);
      if (!taskId && items.length > 0) {
        setSelectedId(items[0].id);
      }
    } catch (err) {
      console.error('Failed to load tasks:', err);
    } finally {
      setTasksLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    if (taskId) {
      setSelectedId(taskId);
    }
  }, [taskId]);

  const activeId = selectedId || taskId;

  const fetchTests = useCallback(async () => {
    if (!activeId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [testsRes, stateRes] = await Promise.all([
        api.getTaskTests(activeId),
        api.getTaskState(activeId),
      ]);
      setTests(testsRes || []);
      setTaskState(stateRes);
      // Auto-expand all runs by default
      if (testsRes && testsRes.length > 0) {
        setExpandedRunIds(new Set(testsRes.map((t) => t.id)));
      }
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to fetch test runs.');
    } finally {
      setLoading(false);
    }
  }, [activeId]);

  useEffect(() => {
    fetchTests();
  }, [fetchTests]);

  const toggleRunExpand = (runId) => {
    setExpandedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) {
        next.delete(runId);
      } else {
        next.add(runId);
      }
      return next;
    });
  };

  const showSkeleton = (tasksLoading && !activeId) || (loading && !tests.length && !error);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Top Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '1rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {activeId && (
            <Link to={`/tasks/${activeId}`} className="btn btn-ghost btn-sm" style={{ padding: '0.3rem 0.5rem' }}>
              <ArrowLeft size={14} />
              <span>Back to Execution</span>
            </Link>
          )}
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            Test Runs & Verification Output
          </h2>
          {tasksList.length > 0 && (
            <select
              className="form-select"
              style={{ width: 'auto', padding: '0.35rem 0.65rem', fontSize: '0.8rem' }}
              value={activeId || ''}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {tasksList.map((t) => (
                <option key={t.id} value={t.id}>
                  #{t.id} — {t.repository_url.replace('https://github.com/', '')}
                </option>
              ))}
            </select>
          )}
        </div>

        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={() => {
            if (activeId) fetchTests();
            else loadTasks();
          }}
          disabled={loading || tasksLoading}
        >
          <RefreshCw size={13} className={loading || tasksLoading ? 'spin-animation' : ''} />
          <span>Refresh Tests</span>
        </button>
      </div>

      {/* Error Alert */}
      {error && (
        <div
          style={{
            padding: '0.75rem 1rem',
            backgroundColor: 'var(--status-error-bg)',
            border: '1px solid var(--status-error-border)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--status-error)',
            fontSize: '0.82rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '0.5rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertTriangle size={15} />
            <span>{error}</span>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
            onClick={fetchTests}
          >
            <RefreshCw size={12} />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Task Summary Context */}
      {taskState && (
        <div
          style={{
            padding: '0.75rem 1rem',
            backgroundColor: 'var(--bg-card)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-md)',
            fontSize: '0.82rem',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <div>
            <span style={{ color: 'var(--text-muted)' }}>Task #{taskState.id}: </span>
            <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{taskState.task_description}</span>
          </div>
          <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>
            {tests.length} {tests.length === 1 ? 'test run executed' : 'test runs executed'}
          </span>
        </div>
      )}

      {/* Test Runs List or Empty State */}
      {showSkeleton ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="skeleton" style={{ height: '120px' }} />
          <div className="skeleton" style={{ height: '120px' }} />
        </div>
      ) : !activeId ? (
        <div className="state-box">
          <CheckSquare size={36} className="state-box-icon" />
          <div className="state-box-title">
            {tasksList.length === 0 ? 'No Execution Tasks Found' : 'No Task Selected'}
          </div>
          <div className="state-box-desc">
            {tasksList.length === 0
              ? 'There are currently no tasks in the queue. Create a new task to execute test runs.'
              : 'Select a task above to inspect verification test runs.'}
          </div>
          {tasksList.length === 0 && (
            <Link to="/new" className="btn btn-primary btn-sm">
              Create New Task
            </Link>
          )}
        </div>
      ) : tests.length === 0 ? (
        <div className="state-box">
          <CheckSquare size={36} className="state-box-icon" />
          <div className="state-box-title">No Test Runs Recorded</div>
          <div className="state-box-desc">
            No test executions have been captured for task #{activeId} yet.
            {taskState?.is_active && ' The agent may still be in investigation or planning.'}
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
          {tests.map((run, idx) => {
            const isExpanded = expandedRunIds.has(run.id);
            return (
              <div key={run.id || idx} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                {/* Run Header */}
                <div
                  onClick={() => toggleRunExpand(run.id)}
                  style={{
                    padding: '0.9rem 1.25rem',
                    backgroundColor: 'var(--bg-card)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    userSelect: 'none',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    {run.passed ? (
                      <CheckCircle2 size={18} color="var(--status-success)" />
                    ) : (
                      <XCircle size={18} color="var(--status-error)" />
                    )}

                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: '0.88rem',
                            fontWeight: 600,
                            color: 'var(--text-primary)',
                          }}
                        >
                          $ {run.command}
                        </span>
                        <span
                          className={`badge ${run.passed ? 'badge-completed' : 'badge-failed'}`}
                          style={{ fontSize: '0.68rem', padding: '0.15rem 0.45rem' }}
                        >
                          {run.passed ? 'PASSED' : 'FAILED'}
                        </span>
                      </div>
                      <div
                        style={{
                          fontSize: '0.75rem',
                          color: 'var(--text-muted)',
                          marginTop: '2px',
                          display: 'flex',
                          gap: '0.75rem',
                        }}
                      >
                        <span>Exit Code: {run.exit_code}</span>
                        {run.duration_seconds !== null && (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                            <Clock size={11} /> {Number(run.duration_seconds).toFixed(2)}s
                          </span>
                        )}
                        <span>
                          {run.started_at ? new Date(run.started_at).toLocaleTimeString() : ''}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div style={{ color: 'var(--text-muted)' }}>
                    {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                  </div>
                </div>

                {/* Terminal Console Output */}
                {isExpanded && (
                  <div
                    style={{
                      borderTop: '1px solid var(--border-subtle)',
                      backgroundColor: '#070B12',
                      padding: '1rem',
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.8rem',
                      lineHeight: 1.5,
                      maxHeight: '400px',
                      overflowY: 'auto',
                    }}
                  >
                    {run.stdout && (
                      <div style={{ marginBottom: run.stderr ? '0.75rem' : 0 }}>
                        <div
                          style={{
                            color: 'var(--accent-cyan)',
                            fontSize: '0.7rem',
                            fontWeight: 600,
                            marginBottom: '0.3rem',
                            textTransform: 'uppercase',
                          }}
                        >
                          Standard Output (stdout):
                        </div>
                        <pre style={{ margin: 0, color: '#E2E8F0', whiteSpace: 'pre-wrap' }}>
                          {run.stdout}
                        </pre>
                      </div>
                    )}

                    {run.stderr && (
                      <div>
                        <div
                          style={{
                            color: 'var(--status-error)',
                            fontSize: '0.7rem',
                            fontWeight: 600,
                            marginBottom: '0.3rem',
                            textTransform: 'uppercase',
                          }}
                        >
                          Standard Error (stderr):
                        </div>
                        <pre style={{ margin: 0, color: '#FCA5A5', whiteSpace: 'pre-wrap' }}>
                          {run.stderr}
                        </pre>
                      </div>
                    )}

                    {!run.stdout && !run.stderr && (
                      <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                        No console output captured for this test run.
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default TestResults;
