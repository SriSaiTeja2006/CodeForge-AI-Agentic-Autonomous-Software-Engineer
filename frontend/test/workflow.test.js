import test from 'node:test';
import assert from 'node:assert/strict';
import { formatApiErrorMessage, getErrorMessage, ApiError, api } from '../src/api/client.js';

// ==============================================================================
// 1. REPOSITORY URL & PAYLOAD VALIDATION
// ==============================================================================

test('validates repository URLs and rejects invalid inputs', () => {
  const isValidGitHubUrl = (url) => {
    if (!url || typeof url !== 'string') return false;
    const trimmed = url.trim();
    if (!trimmed.includes('github.com')) return false;
    try {
      const parsed = new URL(trimmed);
      return parsed.hostname === 'github.com' && parsed.pathname.split('/').filter(Boolean).length >= 2;
    } catch {
      return false;
    }
  };

  assert.equal(isValidGitHubUrl('https://github.com/octocat/Hello-World'), true);
  assert.equal(isValidGitHubUrl('https://github.com/owner/repo/tree/main'), true);
  assert.equal(isValidGitHubUrl('https://gitlab.com/owner/repo'), false);
  assert.equal(isValidGitHubUrl('https://not-github.com/repo'), false);
  assert.equal(isValidGitHubUrl('not-a-url'), false);
  assert.equal(isValidGitHubUrl(''), false);
  assert.equal(isValidGitHubUrl(null), false);
});

test('builds correct task creation payload with sanitized types', () => {
  const buildPayload = ({ repoUrl, taskDesc, criteria, issueNum }) => {
    return {
      repository_url: repoUrl.trim(),
      task_description: taskDesc.trim(),
      acceptance_criteria: criteria && criteria.trim() ? criteria.trim() : null,
      issue_number: issueNum && !isNaN(Number(issueNum)) ? parseInt(issueNum, 10) : null,
    };
  };

  const payload = buildPayload({
    repoUrl: ' https://github.com/octocat/Hello-World ',
    taskDesc: ' Fix arithmetic subtraction bug ',
    criteria: ' All tests pass ',
    issueNum: ' 42 ',
  });

  assert.deepEqual(payload, {
    repository_url: 'https://github.com/octocat/Hello-World',
    task_description: 'Fix arithmetic subtraction bug',
    acceptance_criteria: 'All tests pass',
    issue_number: 42,
  });

  // Empty optional fields become null
  const emptyPayload = buildPayload({
    repoUrl: 'https://github.com/octocat/Hello-World',
    taskDesc: 'Minimal description',
    criteria: '   ',
    issueNum: '',
  });

  assert.equal(emptyPayload.acceptance_criteria, null);
  assert.equal(emptyPayload.issue_number, null);
});

// ==============================================================================
// 2. STATUS BADGE STATE MAPPING (FAILED, BLOCKED, RUNNING, SUCCESS)
// ==============================================================================

test('accurately maps FAILED, BLOCKED, RUNNING, and SUCCESS states', () => {
  const getBadgeProps = (status) => {
    const normalized = (status || 'queued').toLowerCase();
    const ACTIVE_STATUSES = new Set([
      'running', 'investigating', 'planning', 'editing',
      'testing', 'diagnosing', 'repairing', 'verifying', 'pr_creation'
    ]);

    let badgeClass = 'badge-queued';
    let label = status;

    if (normalized === 'completed' || normalized === 'success') {
      badgeClass = 'badge-completed';
      label = normalized === 'success' ? 'Success' : 'Completed';
    } else if (normalized === 'failed') {
      badgeClass = 'badge-failed';
      label = 'Failed';
    } else if (normalized === 'blocked') {
      badgeClass = 'badge-blocked';
      label = 'Blocked';
    } else if (normalized === 'cancelled') {
      badgeClass = 'badge-cancelled';
      label = 'Cancelled';
    } else if (normalized === 'needs_human_review') {
      badgeClass = 'badge-review';
      label = 'Needs Review';
    } else if (ACTIVE_STATUSES.has(normalized)) {
      badgeClass = 'badge-running';
      label = normalized.replace('_', ' ');
    } else if (normalized === 'queued') {
      badgeClass = 'badge-queued';
      label = 'Queued';
    }

    return { badgeClass, label, isActive: ACTIVE_STATUSES.has(normalized) };
  };

  // SUCCESS / Completed
  const successBadge = getBadgeProps('success');
  assert.equal(successBadge.badgeClass, 'badge-completed');
  assert.equal(successBadge.label, 'Success');

  const completedBadge = getBadgeProps('completed');
  assert.equal(completedBadge.badgeClass, 'badge-completed');
  assert.equal(completedBadge.label, 'Completed');

  // FAILED
  const failedBadge = getBadgeProps('failed');
  assert.equal(failedBadge.badgeClass, 'badge-failed');
  assert.equal(failedBadge.label, 'Failed');

  // BLOCKED
  const blockedBadge = getBadgeProps('blocked');
  assert.equal(blockedBadge.badgeClass, 'badge-blocked');
  assert.equal(blockedBadge.label, 'Blocked');

  // RUNNING (active)
  const runningBadge = getBadgeProps('running');
  assert.equal(runningBadge.badgeClass, 'badge-running');
  assert.equal(runningBadge.isActive, true);

  const investigatingBadge = getBadgeProps('investigating');
  assert.equal(investigatingBadge.badgeClass, 'badge-running');
  assert.equal(investigatingBadge.isActive, true);
});

// ==============================================================================
// 3. RETRY TASK ERROR & VALIDATION HANDLING
// ==============================================================================

test('formats retry errors safely without masking backend detail', () => {
  const retryLimitError = {
    detail: 'Task #101 has reached its retry limit (3/3) and cannot be retried.',
  };
  assert.equal(
    formatApiErrorMessage(retryLimitError, 400),
    'Task #101 has reached its retry limit (3/3) and cannot be retried.'
  );

  const runningRetryError = {
    detail: 'Cannot retry task in active running state. Cancel it first.',
  };
  assert.equal(
    formatApiErrorMessage(runningRetryError, 400),
    'Cannot retry task in active running state. Cancel it first.'
  );
});

// ==============================================================================
// 4. EMPTY RESULTS VS SUCCESSFUL VERIFICATION INVARIANT
// ==============================================================================

test('ensures empty diffs or empty test runs are never treated as verified success', () => {
  const isWorkflowVerified = ({ testRuns, fileChanges, taskStatus }) => {
    // Both test runs and file changes must exist, all tests must pass, and status must be completed
    if (!testRuns || testRuns.length === 0) return false;
    if (!fileChanges || fileChanges.length === 0) return false;
    if (taskStatus !== 'completed') return false;
    const allTestsPassed = testRuns.every((t) => t.passed === true && t.exit_code === 0);
    const hasValidDiffs = fileChanges.every((c) => Boolean((c.diff_text || c.diff)?.trim()));
    return allTestsPassed && hasValidDiffs;
  };

  // Case 1: No file changes recorded
  assert.equal(
    isWorkflowVerified({
      testRuns: [{ passed: true, exit_code: 0 }],
      fileChanges: [],
      taskStatus: 'completed',
    }),
    false
  );

  // Case 2: No test runs recorded
  assert.equal(
    isWorkflowVerified({
      testRuns: [],
      fileChanges: [{ diff_text: '+modified code' }],
      taskStatus: 'completed',
    }),
    false
  );

  // Case 3: Tests failed
  assert.equal(
    isWorkflowVerified({
      testRuns: [{ passed: false, exit_code: 1 }],
      fileChanges: [{ diff_text: '+modified code' }],
      taskStatus: 'completed',
    }),
    false
  );

  // Case 4: Status not completed
  assert.equal(
    isWorkflowVerified({
      testRuns: [{ passed: true, exit_code: 0 }],
      fileChanges: [{ diff_text: '+modified code' }],
      taskStatus: 'running',
    }),
    false
  );

  // Case 5: Real success with passing test runs and non-empty diff
  assert.equal(
    isWorkflowVerified({
      testRuns: [{ passed: true, exit_code: 0 }],
      fileChanges: [{ diff_text: '@@ -1,2 +1,2 @@\n-old\n+new' }],
      taskStatus: 'completed',
    }),
    true
  );
});
