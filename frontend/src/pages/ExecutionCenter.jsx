import React, { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  PlayCircle,
  XCircle,
  RotateCcw,
  GitCompare,
  CheckSquare,
  GitPullRequest,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { api, getErrorMessage } from '../api/client';
import usePolling from '../hooks/usePolling';
import StatusBadge from '../components/StatusBadge';
import StageStepper from '../components/StageStepper';
import EventLog from '../components/EventLog';

export function ExecutionCenter() {
  const { taskId } = useParams();
  const navigate = useNavigate();

  const [availableTasks, setAvailableTasks] = useState([]);
  const [tasksLoading, setTasksLoading] = useState(true);
  const [tasksError, setTasksError] = useState(null);
  const [selectedTaskId, setSelectedTaskId] = useState(taskId || null);
  const [events, setEvents] = useState([]);
  const [detailsExpanded, setDetailsExpanded] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState(null);

  // Load available tasks list
  const loadTasks = useCallback(async () => {
    setTasksLoading(true);
    setTasksError(null);
    try {
      const res = await api.listTasks({ page: 1, pageSize: 25 });
      const items = res?.items || [];
      setAvailableTasks(items);
      if (!taskId && items.length > 0) {
        setSelectedTaskId(items[0].id);
      }
    } catch (err) {
      console.error('Failed to load tasks list:', err);
      setTasksError(getErrorMessage(err) || 'Failed to load tasks list.');
    } finally {
      setTasksLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    if (taskId) {
      setSelectedTaskId(taskId);
    } else {
      setSelectedTaskId(null);
    }
  }, [taskId]);

  const activeId = selectedTaskId || taskId;

  // Polling task state function
  const fetchTaskState = useCallback(async () => {
    if (!activeId) return null;
    const [state, evts] = await Promise.all([
      api.getTaskState(activeId),
      api.getTaskEvents(activeId),
    ]);
    setEvents(evts || []);
    return state;
  }, [activeId]);

  // Use the polling hook while activeId is valid
  const {
    data: task,
    loading,
    error,
    refetch,
  } = usePolling(fetchTaskState, {
    interval: 1000,
    enabled: Boolean(activeId),
  });

  const isTaskActive = task?.is_active ?? false;
  const canRetry = task?.can_retry ?? false;
  const isRefreshing = (loading && Boolean(activeId)) || tasksLoading;

  const handleRefresh = async () => {
    setActionError(null);
    if (activeId) {
      await Promise.allSettled([refetch(true), loadTasks()]);
    } else {
      await loadTasks();
    }
  };

  const handleCancel = async () => {
    if (!activeId || !window.confirm(`Are you sure you want to cancel task #${activeId}?`)) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await api.cancelTask(activeId);
      await refetch(true);
    } catch (err) {
      setActionError(getErrorMessage(err) || 'Failed to cancel task.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleRetry = async () => {
    if (!activeId) return;
    setActionLoading(true);
    setActionError(null);
    try {
      await api.retryTask(activeId);
      await refetch(true);
    } catch (err) {
      setActionError(getErrorMessage(err) || 'Failed to retry task.');
    } finally {
      setActionLoading(false);
    }
  };

  const handleSelectTaskChange = (e) => {
    const newId = e.target.value;
    setSelectedTaskId(newId);
    navigate(`/tasks/${newId}`);
  };

  const showSkeleton = (tasksLoading && !activeId) || (loading && !task && !error);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Top Header & Task Selector */}
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
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            Execution Center
          </h2>
          {availableTasks.length > 0 && (
            <select
              className="form-select"
              style={{ width: 'auto', padding: '0.35rem 0.65rem', fontSize: '0.8rem' }}
              value={activeId || ''}
              onChange={handleSelectTaskChange}
            >
              {availableTasks.map((t) => (
                <option key={t.id} value={t.id}>
                  #{t.id} — {t.repository_url.replace('https://github.com/', '')} ({t.status})
                </option>
              ))}
            </select>
          )}
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleRefresh}
            disabled={isRefreshing || actionLoading}
            title="Refresh state immediately"
          >
            <RefreshCw size={13} className={isRefreshing ? 'spin-animation' : ''} />
            <span>Refresh</span>
          </button>

          {isTaskActive && (
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={handleCancel}
              disabled={actionLoading}
            >
              <XCircle size={13} />
              <span>Cancel Task</span>
            </button>
          )}

          {canRetry && (
            <button
              type="button"
              className="btn btn-primary btn-sm"
              onClick={handleRetry}
              disabled={actionLoading}
            >
              <RotateCcw size={13} />
              <span>Retry Task</span>
            </button>
          )}

          <Link
            to={activeId ? `/tasks/${activeId}/changes` : '/changes'}
            className="btn btn-secondary btn-sm"
          >
            <GitCompare size={13} />
            <span>Code Changes ({task?.file_changes_count ?? 0})</span>
          </Link>

          <Link
            to={activeId ? `/tasks/${activeId}/tests` : '/tests'}
            className="btn btn-secondary btn-sm"
          >
            <CheckSquare size={13} />
            <span>Test Runs ({task?.test_runs_count ?? 0})</span>
          </Link>

          <Link
            to={activeId ? `/tasks/${activeId}/pr` : '/pr'}
            className="btn btn-secondary btn-sm"
          >
            <GitPullRequest size={13} />
            <span>Pull Request</span>
          </Link>
        </div>
      </div>

      {/* Action / Fetch Error Alert (when task is loaded or action fails) */}
      {(actionError || (error && task)) && (
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
            <span>{actionError || getErrorMessage(error) || 'Error communicating with task execution engine.'}</span>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
            onClick={() => {
              setActionError(null);
              refetch(true);
            }}
          >
            <RefreshCw size={12} />
            <span>Retry</span>
          </button>
        </div>
      )}

      {/* Main Body */}
      {showSkeleton ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="skeleton" style={{ height: '90px' }} />
          <div className="skeleton" style={{ height: '60px' }} />
          <div className="skeleton" style={{ height: '240px' }} />
        </div>
      ) : tasksError && !activeId ? (
        <div className="state-box" style={{ borderColor: 'var(--status-error-border)' }}>
          <AlertTriangle size={36} color="var(--status-error)" className="state-box-icon" />
          <div className="state-box-title" style={{ color: 'var(--status-error)' }}>
            Failed to Load Tasks
          </div>
          <div className="state-box-desc">
            {tasksError}
          </div>
          <button type="button" className="btn btn-primary btn-sm" onClick={loadTasks}>
            <RefreshCw size={13} />
            <span>Retry</span>
          </button>
        </div>
      ) : !activeId ? (
        <div className="state-box">
          <PlayCircle size={36} className="state-box-icon" />
          <div className="state-box-title">
            {availableTasks.length === 0 ? 'No Execution Tasks Found' : 'No Task Selected'}
          </div>
          <div className="state-box-desc">
            {availableTasks.length === 0
              ? 'There are currently no tasks in the queue. Create a new task to start autonomous development.'
              : 'Select an active or historical task to view its live execution progress, or create a new task.'}
          </div>
          <Link to="/new" className="btn btn-primary btn-sm">
            Create New Task
          </Link>
        </div>
      ) : error && !task ? (
        <div className="state-box" style={{ borderColor: 'var(--status-error-border)' }}>
          <AlertTriangle size={36} color="var(--status-error)" className="state-box-icon" />
          <div className="state-box-title" style={{ color: 'var(--status-error)' }}>
            Failed to Load Task #{activeId}
          </div>
          <div className="state-box-desc">
            {getErrorMessage(error) || 'Error communicating with task execution engine.'}
          </div>
          <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => refetch(true)}>
              <RefreshCw size={13} />
              <span>Retry</span>
            </button>
            <button
              type="button"
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setSelectedTaskId(null);
                navigate('/tasks');
              }}
            >
              Back to Execution Center
            </button>
          </div>
        </div>
      ) : task ? (
        <>
          {/* Task Summary Banner */}
          <div className="card" style={{ padding: '1rem 1.25rem' }}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                flexWrap: 'wrap',
                gap: '0.75rem',
              }}
            >
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.35rem' }}>
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '1.05rem',
                      fontWeight: 700,
                      color: 'var(--accent-blue)',
                    }}
                  >
                    Task #{task.id}
                  </span>
                  <StatusBadge status={task.status} />
                  {isTaskActive && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)' }}>
                      (Polling updates every 2s)
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '0.8rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  <a
                    href={task.repository_url}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      color: 'var(--text-primary)',
                      textDecoration: 'none',
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.3rem',
                      fontFamily: 'var(--font-mono)',
                    }}
                  >
                    <span>{task.repository_url.replace('https://github.com/', '')}</span>
                    <ExternalLink size={12} />
                  </a>

                  {task.issue_number && (
                    <span style={{ color: 'var(--accent-violet)' }}>Issue #{task.issue_number}</span>
                  )}

                  <span>
                    Retries: {task.retry_count} / {task.max_retries}
                  </span>
                </div>
              </div>

              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setDetailsExpanded(!detailsExpanded)}
                style={{ fontSize: '0.75rem', gap: '0.3rem' }}
              >
                <span>{detailsExpanded ? 'Hide Details' : 'Show Details'}</span>
                {detailsExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
            </div>

            {/* Expandable Description & Criteria */}
            {detailsExpanded && (
              <div
                style={{
                  marginTop: '0.9rem',
                  paddingTop: '0.9rem',
                  borderTop: '1px solid var(--border-subtle)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: '0.75rem',
                  fontSize: '0.82rem',
                }}
              >
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>
                    Task Description:
                  </div>
                  <div
                    style={{
                      whiteSpace: 'pre-wrap',
                      backgroundColor: 'var(--bg-surface)',
                      padding: '0.6rem 0.8rem',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--text-primary)',
                    }}
                  >
                    {task.task_description}
                  </div>
                </div>

                {task.acceptance_criteria && (
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>
                      Acceptance Criteria:
                    </div>
                    <div
                      style={{
                        whiteSpace: 'pre-wrap',
                        backgroundColor: 'var(--bg-surface)',
                        padding: '0.6rem 0.8rem',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--text-primary)',
                      }}
                    >
                      {task.acceptance_criteria}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Workflow Stage Stepper */}
          <div className="card" style={{ padding: '0.9rem 1.25rem' }}>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '0.4rem' }}>
              LangGraph Agent Stages
            </div>
            <StageStepper currentStage={task.current_agent_stage} status={task.status} events={events} />
          </div>

          {/* Error Summary Banner (if failed) */}
          {task.error_summary && (
            <div
              style={{
                padding: '0.8rem 1rem',
                backgroundColor: 'var(--status-error-bg)',
                border: '1px solid var(--status-error-border)',
                borderRadius: 'var(--radius-md)',
                color: 'var(--status-error)',
                fontSize: '0.82rem',
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: '0.2rem' }}>Failure / Error Summary:</div>
              <div style={{ fontFamily: 'var(--font-mono)' }}>{task.error_summary}</div>
            </div>
          )}

          {/* Live Event Log */}
          <div className="card">
            <div className="card-header">
              <div>
                <h3 className="card-title">Live Execution Logs</h3>
                <div className="card-subtitle">
                  Real-time events recorded during investigation, planning, patch generation, and testing
                </div>
              </div>
            </div>
            <EventLog events={events} autoScrollEnabled={isTaskActive} />
          </div>
        </>
      ) : null}
    </div>
  );
}

export default ExecutionCenter;
