import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  History as HistoryIcon,
  Filter,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  PlusCircle,
  RefreshCw,
  GitBranch,
} from 'lucide-react';
import { api } from '../api/client';
import StatusBadge from '../components/StatusBadge';

export function History() {
  const [tasks, setTasks] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize] = useState(15);
  const [totalPages, setTotalPages] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTasks = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listTasks({
        page,
        pageSize,
        status: statusFilter || null,
      });
      setTasks(res.items || []);
      setTotalPages(res.total_pages || 1);
      setTotalCount(res.total || 0);
    } catch (err) {
      setError(err.message || 'Failed to load task history.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTasks();
  }, [page, statusFilter]);

  const handleStatusChange = (e) => {
    setStatusFilter(e.target.value);
    setPage(1);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            Task Execution History
          </h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Audit log of all scheduled autonomous engineering tasks and outcomes.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={fetchTasks}
            disabled={loading}
          >
            <RefreshCw size={13} className={loading ? 'spin-animation' : ''} />
            <span>Refresh</span>
          </button>
          <Link to="/new" className="btn btn-primary btn-sm">
            <PlusCircle size={14} />
            <span>New Task</span>
          </Link>
        </div>
      </div>

      {/* Filter Bar */}
      <div
        className="card"
        style={{
          padding: '0.75rem 1rem',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <Filter size={15} color="var(--text-muted)" />
          <span style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
            Status Filter:
          </span>
          <select
            className="form-select"
            style={{ width: 'auto', padding: '0.3rem 0.6rem', fontSize: '0.8rem' }}
            value={statusFilter}
            onChange={handleStatusChange}
          >
            <option value="">All Statuses ({totalCount})</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="needs_human_review">Needs Human Review</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>

        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          Showing {tasks.length} of {totalCount} total tasks
        </div>
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
            gap: '0.5rem',
          }}
        >
          <AlertCircle size={15} />
          <span>{error}</span>
        </div>
      )}

      {/* Table Container */}
      <div className="card" style={{ padding: 0 }}>
        {loading ? (
          <div style={{ padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
            <div className="skeleton" style={{ height: '40px' }} />
            <div className="skeleton" style={{ height: '40px' }} />
            <div className="skeleton" style={{ height: '40px' }} />
          </div>
        ) : tasks.length === 0 ? (
          <div className="state-box" style={{ margin: '1rem' }}>
            <HistoryIcon size={36} className="state-box-icon" />
            <div className="state-box-title">No Tasks Found</div>
            <div className="state-box-desc">
              {statusFilter
                ? `No tasks found matching status '${statusFilter}'.`
                : 'No tasks have been scheduled yet.'}
            </div>
          </div>
        ) : (
          <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ width: '70px' }}>ID</th>
                  <th>Repository</th>
                  <th>Description</th>
                  <th style={{ width: '120px' }}>Status</th>
                  <th style={{ width: '110px' }}>Stage</th>
                  <th style={{ width: '80px' }}>Retries</th>
                  <th style={{ width: '140px' }}>Created</th>
                  <th style={{ width: '130px', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
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
                        <span style={{ marginLeft: '0.35rem', fontSize: '0.72rem', color: 'var(--accent-violet)' }}>
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
                          maxWidth: '380px',
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
                      {t.retry_count} / {t.max_retries}
                    </td>
                    <td style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                      {t.created_at ? new Date(t.created_at).toLocaleDateString() : 'N/A'}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', gap: '0.3rem' }}>
                        <Link
                          to={`/tasks/${t.id}`}
                          className="btn btn-secondary btn-sm"
                          style={{ padding: '0.2rem 0.45rem', fontSize: '0.75rem' }}
                        >
                          View
                        </Link>
                        <Link
                          to={`/tasks/${t.id}/changes`}
                          className="btn btn-ghost btn-sm"
                          style={{ padding: '0.2rem 0.45rem', fontSize: '0.75rem' }}
                          title="View Diffs"
                        >
                          Diff
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Pagination Bar */}
        {totalPages > 1 && (
          <div
            style={{
              padding: '0.75rem 1rem',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              borderTop: '1px solid var(--border-subtle)',
              fontSize: '0.8rem',
            }}
          >
            <span style={{ color: 'var(--text-muted)' }}>
              Page {page} of {totalPages}
            </span>

            <div style={{ display: 'flex', gap: '0.4rem' }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                <ChevronLeft size={14} />
                <span>Previous</span>
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
              >
                <span>Next</span>
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default History;
