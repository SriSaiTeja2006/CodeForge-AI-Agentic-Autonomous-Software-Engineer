import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { GitCompare, FileCode, AlertTriangle, ArrowLeft, RefreshCw } from 'lucide-react';
import { api, getErrorMessage } from '../api/client';
import DiffViewer from '../components/DiffViewer';

export function CodeChanges() {
  const { taskId } = useParams();
  const [tasksList, setTasksList] = useState([]);
  const [selectedId, setSelectedId] = useState(taskId || null);
  const [changes, setChanges] = useState([]);
  const [taskState, setTaskState] = useState(null);
  const [tasksLoading, setTasksLoading] = useState(!taskId);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState(null);

  // Load available tasks if none selected
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

  const fetchChanges = useCallback(async () => {
    if (!activeId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [changesRes, stateRes] = await Promise.all([
        api.getTaskChanges(activeId),
        api.getTaskState(activeId),
      ]);
      setChanges(changesRes || []);
      setTaskState(stateRes);
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to fetch code changes for task.');
    } finally {
      setLoading(false);
    }
  }, [activeId]);

  useEffect(() => {
    fetchChanges();
  }, [fetchChanges]);

  const showSkeleton = (tasksLoading && !activeId) || (loading && !changes.length && !error);

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
            Code Changes & Unified Patches
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
            if (activeId) fetchChanges();
            else loadTasks();
          }}
          disabled={loading || tasksLoading}
        >
          <RefreshCw size={13} className={loading || tasksLoading ? 'spin-animation' : ''} />
          <span>Refresh Diffs</span>
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
            onClick={fetchChanges}
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
          <span style={{ color: 'var(--accent-blue)', fontWeight: 600 }}>
            {changes.length} {changes.length === 1 ? 'file modified' : 'files modified'}
          </span>
        </div>
      )}

      {/* Diffs List or Empty State */}
      {showSkeleton ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="skeleton" style={{ height: '140px' }} />
          <div className="skeleton" style={{ height: '140px' }} />
        </div>
      ) : !activeId ? (
        <div className="state-box">
          <GitCompare size={36} className="state-box-icon" />
          <div className="state-box-title">
            {tasksList.length === 0 ? 'No Execution Tasks Found' : 'No Task Selected'}
          </div>
          <div className="state-box-desc">
            {tasksList.length === 0
              ? 'There are currently no tasks in the queue. Create a new task to generate code changes.'
              : 'Select a task above to inspect generated diffs and patches.'}
          </div>
          {tasksList.length === 0 && (
            <Link to="/new" className="btn btn-primary btn-sm">
              Create New Task
            </Link>
          )}
        </div>
      ) : changes.length === 0 ? (
        <div className="state-box">
          <FileCode size={36} className="state-box-icon" />
          <div className="state-box-title">No File Changes Recorded</div>
          <div className="state-box-desc">
            The autonomous agent has not generated any file modifications for task #{activeId} yet.
            {taskState?.is_active && ' The agent may currently be investigating or planning.'}
          </div>
        </div>
      ) : (
        <div>
          {changes.map((change) => (
            <DiffViewer
              key={change.id || change.relative_file_path || change.file_path}
              filePath={change.relative_file_path || change.file_path}
              diffText={change.diff_text || change.diff}
              changeType={change.change_type || 'modified'}
              summary={change.change_summary || change.summary}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default CodeChanges;
