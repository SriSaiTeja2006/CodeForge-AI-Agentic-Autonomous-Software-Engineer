import React, { useState, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  FolderGit2,
  GitBranch,
  Star,
  GitFork,
  AlertCircle,
  ExternalLink,
  PlusCircle,
  Search,
  Loader2,
  RefreshCw,
} from 'lucide-react';
import { api } from '../api/client';

export function Repositories() {
  const navigate = useNavigate();
  const [repos, setRepos] = useState([]);
  const [inspectedData, setInspectedData] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Manual inspection input
  const [manualUrl, setManualUrl] = useState('');
  const [inspectingManual, setInspectingManual] = useState(false);
  const [manualError, setManualError] = useState(null);

  const fetchRepositories = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listTasks({ page: 1, pageSize: 100 });
      const items = res.items || [];

      // Extract unique repository URLs from backend task history
      const repoMap = new Map();
      items.forEach((task) => {
        const url = task.repository_url;
        if (!repoMap.has(url)) {
          repoMap.set(url, {
            url,
            taskCount: 1,
            lastTaskId: task.id,
            lastStatus: task.status,
            lastUpdated: task.updated_at,
          });
        } else {
          const existing = repoMap.get(url);
          existing.taskCount += 1;
        }
      });

      const uniqueRepos = Array.from(repoMap.values());
      setRepos(uniqueRepos);

      // Auto-inspect first few repos asynchronously
      uniqueRepos.slice(0, 5).forEach((r) => {
        inspectRepo(r.url);
      });
    } catch (err) {
      setError(err.message || 'Failed to load repository data.');
    } finally {
      setLoading(false);
    }
  };

  const inspectRepo = async (repoUrl) => {
    try {
      const data = await api.inspectRepository(repoUrl);
      setInspectedData((prev) => ({ ...prev, [repoUrl]: data }));
    } catch (err) {
      console.warn(`Could not inspect ${repoUrl}:`, err);
    }
  };

  useEffect(() => {
    fetchRepositories();
  }, []);

  const handleManualInspect = async (e) => {
    e.preventDefault();
    if (!manualUrl.trim()) return;

    setInspectingManual(true);
    setManualError(null);
    try {
      const data = await api.inspectRepository(manualUrl.trim());
      setInspectedData((prev) => ({ ...prev, [manualUrl.trim()]: data }));

      // Add to list if not already present
      setRepos((prev) => {
        if (!prev.some((r) => r.url === manualUrl.trim())) {
          return [
            {
              url: manualUrl.trim(),
              taskCount: 0,
              lastTaskId: null,
              lastStatus: null,
              lastUpdated: new Date().toISOString(),
            },
            ...prev,
          ];
        }
        return prev;
      });
      setManualUrl('');
    } catch (err) {
      setManualError(err.message || 'Failed to inspect repository.');
    } finally {
      setInspectingManual(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '1rem' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            Connected Repositories
          </h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Repositories inspected and targeted by CodeForge AI autonomous workflows.
          </p>
        </div>

        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={fetchRepositories}
          disabled={loading}
        >
          <RefreshCw size={13} className={loading ? 'spin-animation' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Manual Inspect Form */}
      <form onSubmit={handleManualInspect} className="card" style={{ padding: '1rem 1.25rem' }}>
        <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
          Inspect a New Repository
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            type="text"
            className="form-input"
            placeholder="https://github.com/owner/repository"
            value={manualUrl}
            onChange={(e) => setManualUrl(e.target.value)}
            disabled={inspectingManual}
          />
          <button
            type="submit"
            className="btn btn-primary"
            disabled={inspectingManual || !manualUrl.trim()}
            style={{ flexShrink: 0 }}
          >
            {inspectingManual ? (
              <>
                <Loader2 size={14} className="spin-animation" />
                <span>Inspecting...</span>
              </>
            ) : (
              <>
                <Search size={14} />
                <span>Inspect</span>
              </>
            )}
          </button>
        </div>
        {manualError && (
          <div style={{ marginTop: '0.5rem', color: 'var(--status-error)', fontSize: '0.78rem' }}>
            {manualError}
          </div>
        )}
      </form>

      {/* Error Banner */}
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

      {/* Repositories Grid or Empty State */}
      {loading ? (
        <div className="grid-2">
          <div className="skeleton" style={{ height: '140px' }} />
          <div className="skeleton" style={{ height: '140px' }} />
        </div>
      ) : repos.length === 0 ? (
        <div className="state-box">
          <FolderGit2 size={36} className="state-box-icon" />
          <div className="state-box-title">No Repositories Tracked Yet</div>
          <div className="state-box-desc">
            Enter a GitHub repository URL above to inspect its metadata, or create a new task.
          </div>
          <Link to="/new" className="btn btn-primary btn-sm">
            <PlusCircle size={14} />
            <span>Create First Task</span>
          </Link>
        </div>
      ) : (
        <div className="grid-2">
          {repos.map((r) => {
            const info = inspectedData[r.url];
            const cleanName = r.url.replace(/^https?:\/\/github\.com\//, '');

            return (
              <div key={r.url} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <FolderGit2 size={18} color="var(--accent-blue)" />
                    <span style={{ fontWeight: 600, fontSize: '0.95rem', fontFamily: 'var(--font-mono)' }}>
                      {cleanName}
                    </span>
                  </div>

                  <a
                    href={r.url}
                    target="_blank"
                    rel="noreferrer"
                    className="btn btn-ghost btn-sm"
                    style={{ padding: '0.2rem 0.4rem' }}
                    title="Open on GitHub"
                  >
                    <ExternalLink size={14} />
                  </a>
                </div>

                {info ? (
                  <>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', minHeight: '36px' }}>
                      {info.description || 'No description provided.'}
                    </p>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                        <GitBranch size={13} color="var(--accent-cyan)" />
                        <code>{info.default_branch || 'main'}</code>
                      </span>
                      {info.language && <span>Language: {info.language}</span>}
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                        <Star size={12} color="var(--status-warning)" />
                        {info.stargazers_count ?? 0}
                      </span>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                        <GitFork size={12} />
                        {info.forks_count ?? 0}
                      </span>
                    </div>
                  </>
                ) : (
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', minHeight: '36px' }}>
                    Inspecting repository details...
                  </div>
                )}

                <div
                  style={{
                    borderTop: '1px solid var(--border-subtle)',
                    paddingTop: '0.6rem',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    fontSize: '0.75rem',
                  }}
                >
                  <span style={{ color: 'var(--text-muted)' }}>
                    {r.taskCount} {r.taskCount === 1 ? 'task executed' : 'tasks executed'}
                  </span>

                  <Link
                    to="/new"
                    className="btn btn-secondary btn-sm"
                    style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                  >
                    <PlusCircle size={12} />
                    <span>New Task</span>
                  </Link>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default Repositories;
