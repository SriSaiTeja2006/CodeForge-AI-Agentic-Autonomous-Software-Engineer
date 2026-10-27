import React from 'react';

const ACTIVE_STATUSES = new Set([
  'running',
  'investigating',
  'planning',
  'editing',
  'testing',
  'diagnosing',
  'repairing',
  'verifying',
  'publishing',
  'pr_creation',
]);

/**
 * Renders a color-coded status badge with animated pulse indicator for active states.
 */
export function StatusBadge({ status = 'queued', size = 'normal' }) {
  const normalized = (status || 'queued').toLowerCase();

  let badgeClass = 'badge-queued';
  let label = status;

  if (normalized === 'completed' || normalized === 'success') {
    badgeClass = 'badge-completed';
    label = normalized === 'success' ? 'Success' : 'Completed';
  } else if (normalized === 'verification_failed') {
    badgeClass = 'badge-failed';
    label = 'Verification Failed';
  } else if (normalized === 'publish_failed') {
    badgeClass = 'badge-failed';
    label = 'Publish Failed';
  } else if (normalized === 'pr_creation_failed') {
    badgeClass = 'badge-failed';
    label = 'PR Creation Failed';
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

  const isActive = ACTIVE_STATUSES.has(normalized);

  return (
    <span
      className={`badge ${badgeClass} ${size === 'sm' ? 'badge-sm' : ''}`}
      style={size === 'sm' ? { fontSize: '0.65rem', padding: '0.15rem 0.45rem' } : undefined}
    >
      {isActive && <span className="pulse-dot" />}
      {label}
    </span>
  );
}

export default StatusBadge;
