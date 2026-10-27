import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Activity,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ArrowRight,
  PlusCircle,
  RefreshCw,
  GitBranch,
} from 'lucide-react';
import { api } from '../api/client';
import StatusBadge from '../components/StatusBadge';

const ACTIVE_STATUSES = new Set([
  'running',
  'investigating',
  'planning',
  'editing',
  'testing',
  'diagnosing',
  'repairing',
  'verifying',
  'pr_creation',
]);

export function Dashboard() {
  const [tasks, setTasks] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [healthInfo, setHealthInfo] = useState(null);

  const fetchDashboardData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [tasksRes, healthRes] = await Promise.allSettled([
        api.listTasks({ page: 1, pageSize: 50 }),
        api.getHealth(),
      ]);

      if (tasksRes.status === 'fulfilled') {
        setTasks(tasksRes.value.items || []);
        setTotalCount(tasksRes.value.total || 0);
      } else {
        throw tasksRes.reason;
      }

      if (healthRes.status === 'fulfilled') {
        setHealthInfo(healthRes.value);
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch dashboard metrics.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, []);

  // Compute live metrics from real tasks returned by API
  const activeCount = tasks.filter((t) => ACTIVE_STATUSES.has((t.status || '').toLowerCase())).length;
  const completedCount = tasks.filter((t) => t.status === 'completed').length;
  const failedCount = tasks.filter((t) => t.status === 'failed' || t.status === 'needs_human_review').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Top Banner & Refresh */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            Engineering Overview
          </h2>
          <p style={{ fontSize: '0.825rem', color: 'var(--text-muted)' }}>
            Real-time status of autonomous coding tasks, worker queues, and LangGraph pipelines.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '0.75rem' }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={fetchDashboardData}
            disabled={loading}
          >
            <RefreshCw size={14} className={loading ? 'spin-animation' : ''} />
            <span>Refresh</span>
          </button>
          <Link to="/new" className="btn btn-primary btn-sm">
            <PlusCircle size={14} />
            <span>New Task</span>
          </Link>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div
          style={{
            padding: '0.9rem 1.25rem',
            backgroundColor: 'var(--status-error-bg)',
            border: '1px solid var(--status-error-border)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--status-error)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: '0.85rem',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertTriangle size={16} />
            <span>{error}</span>
          </div>
          <button type="button" className="btn btn-sm btn-danger" onClick={fetchDashboardData}>
            Retry
          </button>
        </div>
      )}

      {/* Real Metric Cards */}
      <div className="grid-4">
        <div className="stat-card">
          <div className="stat-label">
            <span>Total Tasks</span>
            <Clock size={16} color="var(--accent-blue)" />
          </div>
          <div className="stat-value">{loading ? '...' : totalCount}</div>
          <div className="stat-description">All scheduled repository jobs</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">
            <span>Active Executions</span>
            <Activity size={16} color="var(--accent-cyan)" />
          </div>
          <div className="stat-value" style={{ color: 'var(--accent-cyan)' }}>
            {loading ? '...' : activeCount}
          </div>
          <div className="stat-description">In-progress agent workflows</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">
            <span>Completed</span>
            <CheckCircle2 size={16} color="var(--status-success)" />
          </div>
          <div className="stat-value" style={{ color: 'var(--status-success)' }}>
            {loading ? '...' : completedCount}
          </div>
          <div className="stat-description">Verified and ready for PR</div>
        </div>

        <div className="stat-card">
          <div className="stat-label">
            <span>Needs Attention</span>
            <AlertTriangle size={16} color="var(--status-error)" />
          </div>
          <div className="stat-value" style={{ color: 'var(--status-error)' }}>
            {loading ? '...' : failedCount}
          </div>
          <div className="stat-description">Failed or review requested</div>
        </div>
      </div>

      {/* Recent Tasks Card */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3 className="card-title">Recent Tasks</h3>
            <div className="card-subtitle">Active and recently executed engineering jobs</div>
          </div>
          <Link
            to="/history"
            className="btn btn-ghost btn-sm"
            style={{ color: 'var(--accent-blue)', gap: '0.3rem' }}
          >
            <span>View All History</span>
            <ArrowRight size={14} />
          </Link>
        </div>

        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', padding: '1rem 0' }}>
            <div className="skeleton" style={{ height: '40px' }} />
            <div className="skeleton" style={{ height: '40px' }} />
            <div className="skeleton" style={{ height: '40px' }} />
          </div>
        ) : tasks.length === 0 ? (
          <div className="state-box">
            <GitBranch size={32} className="state-box-icon" />
            <div className="state-box-title">No tasks found</div>
            <div className="state-box-desc">
              Get started by creating your first autonomous coding task with a GitHub repository.
            </div>
            <Link to="/new" className="btn btn-primary btn-sm">
              <PlusCircle size={14} />
              <span>Create Task</span>
            </Link>
          </div>
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '80px' }}>Task ID</th>
                  <th>Repository</th>
                  <th>Task Description</th>
                  <th style={{ width: '130px' }}>Status</th>
                  <th style={{ width: '120px' }}>Stage</th>
                  <th style={{ width: '140px' }}>Created</th>
                  <th style={{ width: '90px', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {tasks.slice(0, 10).map((t) => (
                  <tr key={t.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                      <Link
                        to={`/tasks/${t.id}`}
                        style={{ color: 'var(--accent-blue)', textDecoration: 'none' }}
                      >
                        #{t.id}
                      </Link>
                    </td>
                    <td>
                      <span
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: '0.8rem',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {t.repository_url?.replace(/^https?:\/\/github\.com\//, '') || t.repository_url}
                      </span>
                      {t.issue_number && (
                        <span
                          style={{
                            marginLeft: '0.4rem',
                            fontSize: '0.72rem',
                            color: 'var(--accent-violet)',
                          }}
                        >
                          #{t.issue_number}
                        </span>
                      )}
                    </td>
                    <td>
                      <span
                        style={{
                          display: '-webkit-box',
                          WebkitLineClamp: 1,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                          maxWidth: '360px',
                        }}
                        title={t.task_description}
                      >
                        {t.task_description}
                      </span>
                    </td>
                    <td>
                      <StatusBadge status={t.status} size="sm" />
                    </td>
                    <td style={{ fontSize: '0.78rem', textTransform: 'capitalize', color: 'var(--text-muted)' }}>
                      {t.current_agent_stage || 'queued'}
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {t.created_at ? new Date(t.created_at).toLocaleString() : 'N/A'}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <Link to={`/tasks/${t.id}`} className="btn btn-secondary btn-sm" style={{ padding: '0.2rem 0.5rem' }}>
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

export default Dashboard;
