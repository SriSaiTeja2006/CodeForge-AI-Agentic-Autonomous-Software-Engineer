import React, { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  GitPullRequest,
  CheckCircle2,
  XCircle,
  AlertCircle,
  Clock,
  ArrowLeft,
  ExternalLink,
  Copy,
  Check,
  ShieldCheck,
  Send,
  Loader2,
  ShieldAlert,
  FileCode,
  Terminal,
  Lock,
  RefreshCw,
} from 'lucide-react';
import { api, getErrorMessage } from '../api/client';

export function PullRequest() {
  const { taskId } = useParams();
  const [tasksList, setTasksList] = useState([]);
  const [selectedId, setSelectedId] = useState(taskId || null);
  const [taskState, setTaskState] = useState(null);
  const [prPreview, setPrPreview] = useState(null);
  const [changes, setChanges] = useState([]);
  const [tests, setTests] = useState([]);
  const [tasksLoading, setTasksLoading] = useState(!taskId);
  const [loading, setLoading] = useState(Boolean(taskId));
  const [error, setError] = useState(null);

  // Form & Action states
  const [prTitle, setPrTitle] = useState('');
  const [prBody, setPrBody] = useState('');
  const [isDraft, setIsDraft] = useState(false);
  const [humanApproved, setHumanApproved] = useState(false);
  const [submittingPr, setSubmittingPr] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [createdPr, setCreatedPr] = useState(null);
  const [copiedCmd, setCopiedCmd] = useState(false);

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

  const displayTasksList = React.useMemo(() => {
    if (taskState && !tasksList.some((t) => String(t.id) === String(taskState.id))) {
      return [{ id: taskState.id, repository_url: taskState.repository_url }, ...tasksList];
    }
    return tasksList;
  }, [taskState, tasksList]);

  const loadData = useCallback(async () => {
    if (!activeId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    setActionError(null);
    try {
      const [previewRes, stateRes, changesRes, testsRes] = await Promise.all([
        api.getTaskPrPreview(activeId),
        api.getTaskState(activeId),
        api.getTaskChanges(activeId),
        api.getTaskTests(activeId),
      ]);

      setPrPreview(previewRes);
      setTaskState(stateRes);
      setChanges(changesRes || []);
      setTests(testsRes || []);

      if (previewRes.suggested_title) {
        setPrTitle(previewRes.suggested_title);
      }
      if (previewRes.suggested_body) {
        setPrBody(previewRes.suggested_body);
      }
      if (previewRes.is_approved) {
        setHumanApproved(true);
      }
      if (previewRes.existing_pr) {
        setCreatedPr(previewRes.existing_pr);
      } else {
        setCreatedPr(null);
      }
    } catch (err) {
      setError(getErrorMessage(err) || 'Failed to prepare pull request metadata.');
    } finally {
      setLoading(false);
    }
  }, [activeId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Determine High-Level PR State:
  // 'unavailable' | 'not_created' | 'pending_approval' | 'actually_created'
  const effectivePr = createdPr || (taskState?.pr_url ? {
    pr_number: taskState.pr_number,
    pr_url: taskState.pr_url,
    title: prPreview?.suggested_title || `Pull Request #${taskState.pr_number}`,
    body: prPreview?.suggested_body || '',
    head_branch: taskState.source_branch || prPreview?.head_branch || `codeforge/task-${activeId}`,
    base_branch: taskState.target_branch || prPreview?.base_branch || 'main',
    state: 'open',
    is_draft: false,
    created_at: taskState.updated_at,
  } : null);

  let prState = 'unavailable';
  let stateReason = '';

  if (effectivePr) {
    prState = 'actually_created';
  } else if (!taskState) {
    prState = 'unavailable';
    stateReason = 'Select a valid task to inspect pull request readiness.';
  } else if (taskState.status === 'verification_failed') {
    prState = 'not_created';
    stateReason = taskState.error_summary || `Task #${taskState.id} verification failed: test suite did not pass.`;
  } else if (taskState.status === 'publish_failed') {
    prState = 'not_created';
    stateReason = taskState.error_summary || `Task #${taskState.id} branch publication failed.`;
  } else if (taskState.status === 'pr_creation_failed') {
    prState = 'not_created';
    stateReason = taskState.error_summary || `Task #${taskState.id} pull request creation failed on GitHub.`;
  } else if (taskState.is_active) {
    prState = 'unavailable';
    stateReason = `Task #${taskState.id} is actively executing (${taskState.current_agent_stage}). Pull requests cannot be initiated until workflow verification completes.`;
  } else if (taskState.status === 'cancelled') {
    prState = 'unavailable';
    stateReason = `Task #${taskState.id} was cancelled before verification.`;
  } else if (taskState.status === 'failed') {
    prState = 'not_created';
    stateReason = taskState.error_summary || `Task #${taskState.id} failed verification or exceeded repair limits.`;
  } else if (prPreview && !prPreview.is_ready) {
    prState = 'not_created';
    stateReason = prPreview.readiness_issues?.join('; ') || 'Task is not eligible for PR creation.';
  } else if (prPreview && !prPreview.safety_passed) {
    prState = 'not_created';
    stateReason = `Security check blocked: ${prPreview.safety_violations?.join('; ')}`;
  } else if (taskState.status === 'completed' || taskState.status === 'needs_human_review') {
    prState = 'pending_approval';
  }

  const branchName = prPreview?.head_branch || `codeforge/task-${activeId}`;

  const copyGitCommand = () => {
    const cmd = `git fetch origin ${branchName} && git checkout ${branchName}`;
    navigator.clipboard.writeText(cmd).then(() => {
      setCopiedCmd(true);
      setTimeout(() => setCopiedCmd(false), 2000);
    });
  };

  const handleCreatePr = async (e) => {
    e.preventDefault();
    if (!humanApproved) {
      setActionError('You must check the box to confirm human approval prior to opening a pull request.');
      return;
    }

    setSubmittingPr(true);
    setActionError(null);

    try {
      const res = await api.createTaskPr(activeId, {
        approved: true,
        title: prTitle.trim(),
        body: prBody.trim(),
        draft: isDraft,
      });

      setCreatedPr(res);
      await loadData();
    } catch (err) {
      setActionError(getErrorMessage(err) || 'Failed to create pull request on GitHub.');
    } finally {
      setSubmittingPr(false);
    }
  };

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
            Pull Request Verification & Preparation
          </h2>
          {displayTasksList.length > 0 && (
            <select
              className="form-select"
              style={{ width: 'auto', padding: '0.35rem 0.65rem', fontSize: '0.8rem' }}
              value={activeId ? String(activeId) : ''}
              onChange={(e) => setSelectedId(e.target.value)}
            >
              {displayTasksList.map((t) => (
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
            if (activeId) loadData();
            else loadTasks();
          }}
          disabled={loading || tasksLoading}
        >
          <RefreshCw size={13} className={loading || tasksLoading ? 'spin-animation' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Global / Action Errors */}
      {(error || actionError) && (
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
            <AlertCircle size={15} />
            <span>{actionError || error}</span>
          </div>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            style={{ padding: '0.2rem 0.5rem', fontSize: '0.75rem' }}
            onClick={() => {
              if (activeId) loadData();
              else loadTasks();
            }}
          >
            <RefreshCw size={12} />
            <span>Retry</span>
          </button>
        </div>
      )}

      {(tasksLoading && !activeId) || (loading && !prPreview && !error) ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="skeleton" style={{ height: '90px' }} />
          <div className="skeleton" style={{ height: '200px' }} />
        </div>
      ) : !activeId ? (
        <div className="state-box">
          <GitPullRequest size={36} className="state-box-icon" />
          <div className="state-box-title">
            {tasksList.length === 0 ? 'No Execution Tasks Found' : 'No Task Selected'}
          </div>
          <div className="state-box-desc">
            {tasksList.length === 0
              ? 'There are currently no tasks in the queue. Create a new task to prepare a pull request.'
              : 'Select a task above to prepare or view its pull request.'}
          </div>
          {tasksList.length === 0 && (
            <Link to="/new" className="btn btn-primary btn-sm">
              Create New Task
            </Link>
          )}
        </div>
      ) : (
        <>
          {/* ================================================================= */}
          {/* 1. STATE: ACTUALLY CREATED */}
          {/* ================================================================= */}
          {prState === 'actually_created' && effectivePr && (
            <div
              className="card"
              style={{
                borderColor: 'var(--status-success-border)',
                backgroundColor: 'rgba(16, 185, 129, 0.05)',
                display: 'flex',
                flexDirection: 'column',
                gap: '1rem',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <CheckCircle2 size={24} color="var(--status-success)" />
                  <div>
                    <div style={{ fontWeight: 700, color: 'var(--text-primary)', fontSize: '1.05rem' }}>
                      GitHub Pull Request #{effectivePr.pr_number} Created
                    </div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                      Verified changes opened on branch <code>{effectivePr.head_branch}</code> against <code>{effectivePr.base_branch}</code>.
                    </div>
                  </div>
                </div>

                <a
                  href={effectivePr.pr_url}
                  target="_blank"
                  rel="noreferrer"
                  className="btn btn-primary"
                >
                  <span>View on GitHub</span>
                  <ExternalLink size={14} />
                </a>
              </div>

              <div className="grid-4" style={{ fontSize: '0.78rem', borderTop: '1px solid var(--border-subtle)', paddingTop: '0.75rem' }}>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Status: </span>
                  <span className="badge badge-completed">{effectivePr.state.toUpperCase()}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Draft: </span>
                  <span>{effectivePr.is_draft ? 'Yes' : 'No'}</span>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Working Branch: </span>
                  <code>{effectivePr.head_branch}</code>
                </div>
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Target: </span>
                  <code>{effectivePr.base_branch}</code>
                </div>
              </div>
            </div>
          )}

          {/* ================================================================= */}
          {/* 2. STATE: PENDING APPROVAL & CREATION */}
          {/* ================================================================= */}
          {prState === 'pending_approval' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
              {/* Verification & Safety Cards */}
              <div className="grid-2">
                {/* Verified Changes Card */}
                <div className="card">
                  <div className="card-header">
                    <h3 className="card-title">
                      <FileCode size={16} color="var(--accent-blue)" />
                      <span>Verified Changes ({changes.length})</span>
                    </h3>
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                    {changes.map((c) => (
                      <div
                        key={c.id || c.file_path}
                        style={{
                          display: 'flex',
                          justifyContent: 'space-between',
                          padding: '0.35rem 0.5rem',
                          backgroundColor: 'var(--bg-surface)',
                          borderRadius: 'var(--radius-sm)',
                        }}
                      >
                        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                          {c.file_path}
                        </span>
                        <span className="badge badge-queued" style={{ textTransform: 'capitalize' }}>
                          {c.change_type}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Test Run Evidence Card */}
                <div className="card">
                  <div className="card-header">
                    <h3 className="card-title">
                      <Terminal size={16} color="var(--accent-cyan)" />
                      <span>Test Verification Evidence</span>
                    </h3>
                  </div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                    {tests.length === 0 ? (
                      <div style={{ color: 'var(--text-muted)' }}>No automated tests recorded.</div>
                    ) : (
                      tests.map((t, idx) => (
                        <div
                          key={t.id || idx}
                          style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            padding: '0.35rem 0.5rem',
                            backgroundColor: 'var(--bg-surface)',
                            borderRadius: 'var(--radius-sm)',
                            alignItems: 'center',
                          }}
                        >
                          <span style={{ fontFamily: 'var(--font-mono)' }}>$ {t.command}</span>
                          <span className={`badge ${t.passed ? 'badge-completed' : 'badge-failed'}`}>
                            {t.passed ? 'PASS (0)' : `FAIL (${t.exit_code})`}
                          </span>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>

              {/* Safety & Credential Scan Card */}
              <div
                className="card"
                style={{
                  borderColor: prPreview?.safety_passed ? 'var(--status-success-border)' : 'var(--status-error-border)',
                  backgroundColor: prPreview?.safety_passed ? 'rgba(16, 185, 129, 0.04)' : 'var(--status-error-bg)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                  {prPreview?.safety_passed ? (
                    <>
                      <ShieldCheck size={20} color="var(--status-success)" />
                      <div style={{ fontSize: '0.82rem', color: 'var(--text-primary)' }}>
                        <strong>Automated Secret Scan Passed:</strong> Verified clean diff with no private keys,
                        access tokens, or sensitive configuration files.
                      </div>
                    </>
                  ) : (
                    <>
                      <ShieldAlert size={20} color="var(--status-error)" />
                      <div style={{ fontSize: '0.82rem', color: 'var(--status-error)' }}>
                        <strong>Security Violations Detected:</strong>{' '}
                        {prPreview?.safety_violations?.join(', ')}
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Human Approval Form */}
              <form onSubmit={handleCreatePr} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div className="card-header" style={{ marginBottom: '0.25rem' }}>
                  <div>
                    <h3 className="card-title">
                      <Lock size={16} color="var(--accent-violet)" />
                      <span>Human Review & Approval Gate</span>
                    </h3>
                    <div className="card-subtitle">
                      Explicit human confirmation is required prior to pushing code or creating a GitHub pull request.
                    </div>
                  </div>
                </div>

                {/* Working branch checkout command */}
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', backgroundColor: 'var(--bg-surface)', padding: '0.6rem 0.8rem', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem' }}>
                  <div>
                    <span style={{ color: 'var(--text-muted)' }}>Working Branch: </span>
                    <code style={{ color: 'var(--accent-cyan)' }}>{branchName}</code>
                  </div>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={copyGitCommand}
                    style={{ padding: '0.2rem 0.5rem' }}
                  >
                    {copiedCmd ? <Check size={12} color="var(--status-success)" /> : <Copy size={12} />}
                    <span>{copiedCmd ? 'Copied' : 'Copy git checkout'}</span>
                  </button>
                </div>

                {/* PR Title */}
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label" htmlFor="pr-title">
                    <span>Pull Request Title</span>
                  </label>
                  <input
                    id="pr-title"
                    type="text"
                    className="form-input"
                    value={prTitle}
                    onChange={(e) => setPrTitle(e.target.value)}
                    disabled={submittingPr}
                  />
                </div>

                {/* PR Body */}
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <label className="form-label" htmlFor="pr-body">
                    <span>Pull Request Description Markdown</span>
                  </label>
                  <textarea
                    id="pr-body"
                    className="form-textarea"
                    style={{ minHeight: '160px', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}
                    value={prBody}
                    onChange={(e) => setPrBody(e.target.value)}
                    disabled={submittingPr}
                  />
                </div>

                {/* Draft Option & Human Approval Checkbox */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem', padding: '0.75rem', backgroundColor: 'var(--bg-sidebar)', borderRadius: 'var(--radius-sm)' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.82rem', cursor: 'pointer', color: 'var(--text-primary)' }}>
                    <input
                      type="checkbox"
                      checked={humanApproved}
                      onChange={(e) => setHumanApproved(e.target.checked)}
                      disabled={submittingPr}
                    />
                    <span>
                      <strong>I explicitly confirm human approval:</strong> I have verified the diff,
                      safety checks, and test evidence, and authorize creating this pull request on GitHub.
                    </span>
                  </label>

                  <label style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', fontSize: '0.8rem', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                    <input
                      type="checkbox"
                      checked={isDraft}
                      onChange={(e) => setIsDraft(e.target.checked)}
                      disabled={submittingPr}
                    />
                    <span>Open as a draft pull request</span>
                  </label>
                </div>

                {/* Submit Button */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '0.5rem', borderTop: '1px solid var(--border-subtle)' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Notice: CodeForge AI strictly never automatically merges pull requests.
                  </div>

                  <button
                    type="submit"
                    className="btn btn-primary"
                    disabled={submittingPr || !humanApproved || !prPreview?.safety_passed}
                  >
                    {submittingPr ? (
                      <>
                        <Loader2 size={15} className="spin-animation" />
                        <span>Creating PR on GitHub...</span>
                      </>
                    ) : (
                      <>
                        <Send size={15} />
                        <span>Approve & Open Pull Request</span>
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          )}

          {/* ================================================================= */}
          {/* 3. STATE: NOT CREATED */}
          {/* ================================================================= */}
          {prState === 'not_created' && (
            <div className="state-box">
              <AlertCircle size={36} color="var(--status-error)" className="state-box-icon" />
              <div className="state-box-title">Pull Request Not Created</div>
              <div className="state-box-desc">{stateReason}</div>
              <div style={{ display: 'flex', gap: '0.6rem', marginTop: '0.5rem' }}>
                <Link to={`/tasks/${activeId}`} className="btn btn-secondary btn-sm">
                  View Task Execution Details
                </Link>
                {taskState?.can_retry && (
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    onClick={async () => {
                      try {
                        await api.retryTask(activeId);
                        await loadData();
                      } catch (err) {
                        setActionError(getErrorMessage(err));
                      }
                    }}
                  >
                    Retry Task
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ================================================================= */}
          {/* 4. STATE: UNAVAILABLE */}
          {/* ================================================================= */}
          {prState === 'unavailable' && (
            <div className="state-box">
              <Clock size={36} color="var(--text-muted)" className="state-box-icon" />
              <div className="state-box-title">Pull Request Unavailable</div>
              <div className="state-box-desc">{stateReason}</div>
              <Link to={`/tasks/${activeId}`} className="btn btn-secondary btn-sm">
                Monitor Live Progress
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default PullRequest;
