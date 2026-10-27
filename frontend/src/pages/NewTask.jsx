import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  GitBranch,
  CheckCircle2,
  AlertCircle,
  FileText,
  Search,
  ListFilter,
  Send,
  Loader2,
} from 'lucide-react';
import { api, getErrorMessage } from '../api/client';

export function NewTask() {
  const navigate = useNavigate();

  // Form states
  const [repositoryUrl, setRepositoryUrl] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [acceptanceCriteria, setAcceptanceCriteria] = useState('');
  const [issueNumber, setIssueNumber] = useState('');

  // Validation & inspection states
  const [validatingRepo, setValidatingRepo] = useState(false);
  const [repoValidation, setRepoValidation] = useState(null);
  const [repoError, setRepoError] = useState(null);

  // Issues lookup
  const [fetchingIssues, setFetchingIssues] = useState(false);
  const [issuesList, setIssuesList] = useState([]);
  const [selectedIssue, setSelectedIssue] = useState(null);

  // Submission states
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [formErrors, setFormErrors] = useState({});

  // Validate repository URL with backend
  const handleValidateRepo = async () => {
    if (!repositoryUrl.trim()) {
      setRepoError('Please enter a GitHub repository URL.');
      return;
    }

    setValidatingRepo(true);
    setRepoError(null);
    setRepoValidation(null);

    try {
      const res = await api.validateRepository(repositoryUrl.trim());
      setRepoValidation(res);
      // Fetch open issues automatically for quick selection
      if (res && res.owner && res.repo) {
        fetchIssuesForRepo(`${res.owner}/${res.repo}`);
      }
    } catch (err) {
      setRepoError(getErrorMessage(err) || 'Repository validation failed.');
    } finally {
      setValidatingRepo(false);
    }
  };

  const fetchIssuesForRepo = async (repoCoords) => {
    setFetchingIssues(true);
    try {
      const issues = await api.getIssues(repoCoords);
      setIssuesList(Array.isArray(issues) ? issues : []);
    } catch {
      setIssuesList([]);
    } finally {
      setFetchingIssues(false);
    }
  };

  const handleSelectIssue = (issue) => {
    setSelectedIssue(issue);
    setIssueNumber(String(issue.number));
    if (!taskDescription.trim()) {
      setTaskDescription(`Fix issue #${issue.number}: ${issue.title}\n\n${issue.body || ''}`.trim());
    }
  };

  const validateForm = () => {
    const errors = {};
    if (!repositoryUrl.trim()) {
      errors.repositoryUrl = 'Repository URL is required.';
    } else if (!repositoryUrl.includes('github.com')) {
      errors.repositoryUrl = 'Must be a valid GitHub repository URL.';
    }

    if (!taskDescription.trim()) {
      errors.taskDescription = 'Task description is required.';
    } else if (taskDescription.trim().length < 5) {
      errors.taskDescription = 'Task description must be at least 5 characters.';
    }

    if (issueNumber && isNaN(Number(issueNumber))) {
      errors.issueNumber = 'Issue number must be an integer.';
    }

    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!validateForm()) return;

    setSubmitting(true);
    setSubmitError(null);

    const targetRepoUrl = (repoValidation?.normalized_url || repositoryUrl).trim();
    const payload = {
      repository_url: targetRepoUrl,
      task_description: taskDescription.trim(),
      acceptance_criteria: acceptanceCriteria.trim() || null,
      issue_number: issueNumber && !isNaN(Number(issueNumber)) ? parseInt(issueNumber, 10) : null,
    };

    try {
      const createdTask = await api.createTask(payload);
      if (createdTask && createdTask.id) {
        navigate(`/tasks/${createdTask.id}`);
      } else {
        throw new Error('Task created but received invalid response format.');
      }
    } catch (err) {
      setSubmitError(getErrorMessage(err) || 'Failed to schedule task.');
      setSubmitting(false);
    }
  };

  return (
    <div style={{ maxWidth: '840px', margin: '0 auto' }}>
      <div style={{ marginBottom: '1.5rem' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
          Create Autonomous Engineering Task
        </h2>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          Specify a repository and task objectives. The LangGraph agent will investigate the code,
          generate patches, run tests, and verify results.
        </p>
      </div>

      {submitError && (
        <div
          style={{
            padding: '0.8rem 1.2rem',
            backgroundColor: 'var(--status-error-bg)',
            border: '1px solid var(--status-error-border)',
            borderRadius: 'var(--radius-md)',
            color: 'var(--status-error)',
            marginBottom: '1.25rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.6rem',
            fontSize: '0.85rem',
          }}
        >
          <AlertCircle size={16} />
          <span>{getErrorMessage(submitError)}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
        {/* Repository URL */}
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="repo-url">
            <span>Repository URL *</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>HTTPS or SSH format</span>
          </label>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <input
              id="repo-url"
              type="text"
              className="form-input"
              placeholder="https://github.com/owner/repository"
              value={repositoryUrl}
              onChange={(e) => {
                setRepositoryUrl(e.target.value);
                setRepoValidation(null);
                setRepoError(null);
              }}
              disabled={submitting}
            />
            <button
              type="button"
              className="btn btn-secondary"
              onClick={handleValidateRepo}
              disabled={validatingRepo || submitting || !repositoryUrl.trim()}
              style={{ flexShrink: 0 }}
            >
              {validatingRepo ? (
                <>
                  <Loader2 size={14} className="spin-animation" />
                  <span>Checking...</span>
                </>
              ) : (
                <>
                  <Search size={14} />
                  <span>Validate</span>
                </>
              )}
            </button>
          </div>
          {formErrors.repositoryUrl && <span className="form-error">{formErrors.repositoryUrl}</span>}

          {/* Validation Feedback */}
          {repoValidation && (
            <div
              style={{
                marginTop: '0.5rem',
                padding: '0.6rem 0.8rem',
                backgroundColor: 'var(--status-success-bg)',
                border: '1px solid var(--status-success-border)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.78rem',
                color: 'var(--text-primary)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <CheckCircle2 size={16} color="var(--status-success)" />
              <div>
                <strong>Validated:</strong> {repoValidation.owner}/{repoValidation.repo} (Branch:{' '}
                <code>{repoValidation.default_branch || 'main'}</code>)
              </div>
            </div>
          )}

          {repoError && (
            <div
              style={{
                marginTop: '0.5rem',
                padding: '0.6rem 0.8rem',
                backgroundColor: 'var(--status-error-bg)',
                border: '1px solid var(--status-error-border)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.78rem',
                color: 'var(--status-error)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
              }}
            >
              <AlertCircle size={16} />
              <span>{getErrorMessage(repoError)}</span>
            </div>
          )}
        </div>

        {/* Issue Selection Helper */}
        {issuesList.length > 0 && (
          <div
            style={{
              padding: '0.75rem',
              backgroundColor: 'var(--bg-surface)',
              borderRadius: 'var(--radius-md)',
              border: '1px solid var(--border-subtle)',
            }}
          >
            <div
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: '0.5rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.4rem',
              }}
            >
              <ListFilter size={14} color="var(--accent-violet)" />
              <span>Select an Open Issue to Autofill (Optional)</span>
            </div>
            <div style={{ maxHeight: '140px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
              {issuesList.map((issue) => (
                <div
                  key={issue.number}
                  onClick={() => handleSelectIssue(issue)}
                  style={{
                    padding: '0.4rem 0.6rem',
                    borderRadius: 'var(--radius-sm)',
                    backgroundColor:
                      selectedIssue?.number === issue.number ? 'var(--accent-blue-subtle)' : 'var(--bg-card)',
                    border: '1px solid',
                    borderColor:
                      selectedIssue?.number === issue.number ? 'var(--accent-blue)' : 'var(--border-subtle)',
                    cursor: 'pointer',
                    fontSize: '0.78rem',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <span style={{ color: 'var(--accent-blue)', fontWeight: 600 }}>#{issue.number}</span>
                    <span style={{ color: 'var(--text-primary)' }}>{issue.title}</span>
                  </div>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                    by @{issue.author || 'author'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Issue Number Input */}
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="issue-number">
            <span>Issue Number (Optional)</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>GitHub issue ID</span>
          </label>
          <input
            id="issue-number"
            type="number"
            className="form-input"
            placeholder="e.g. 42"
            value={issueNumber}
            onChange={(e) => setIssueNumber(e.target.value)}
            disabled={submitting}
          />
          {formErrors.issueNumber && <span className="form-error">{formErrors.issueNumber}</span>}
        </div>

        {/* Task Description */}
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="task-description">
            <span>Task Description *</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              Explain the bug or feature clearly
            </span>
          </label>
          <textarea
            id="task-description"
            className="form-textarea"
            style={{ minHeight: '120px' }}
            placeholder="Describe the issue, suspected files, or required fix in detail..."
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            disabled={submitting}
          />
          {formErrors.taskDescription && <span className="form-error">{formErrors.taskDescription}</span>}
        </div>

        {/* Acceptance Criteria */}
        <div className="form-group" style={{ marginBottom: 0 }}>
          <label className="form-label" htmlFor="acceptance-criteria">
            <span>Acceptance Criteria (Optional)</span>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              Conditions for successful verification
            </span>
          </label>
          <textarea
            id="acceptance-criteria"
            className="form-textarea"
            style={{ minHeight: '80px' }}
            placeholder="e.g. All unit tests in tests/test_calc.py pass without errors."
            value={acceptanceCriteria}
            onChange={(e) => setAcceptanceCriteria(e.target.value)}
            disabled={submitting}
          />
        </div>

        {/* Action Controls */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'flex-end',
            gap: '0.75rem',
            paddingTop: '0.5rem',
            borderTop: '1px solid var(--border-subtle)',
          }}
        >
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => navigate('/')}
            disabled={submitting}
          >
            Cancel
          </button>
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? (
              <>
                <Loader2 size={16} className="spin-animation" />
                <span>Scheduling Task...</span>
              </>
            ) : (
              <>
                <Send size={16} />
                <span>Schedule & Execute</span>
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

export default NewTask;
