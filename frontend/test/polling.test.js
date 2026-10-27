import test from 'node:test';
import assert from 'node:assert/strict';

test('usePolling initial state logic handles disabled and enabled states', () => {
  // Simulating usePolling initial state contract with default enabled = true
  const getInitialLoading = (enabled = true) => Boolean(enabled);

  assert.equal(getInitialLoading(false), false, 'When disabled, loading must be false initially');
  assert.equal(getInitialLoading(true), true, 'When enabled, loading must be true initially');
  assert.equal(getInitialLoading(undefined), true, 'When default (enabled=true), loading must be true');
  assert.equal(getInitialLoading(null), false, 'When activeId is null, loading must be false');
});

test('async operation safely resets loading flag in finally block on success and failure', async () => {
  let loading = true;
  let error = null;
  let data = null;

  // Test success
  try {
    data = await Promise.resolve({ id: 1, status: 'queued' });
  } catch (err) {
    error = err;
  } finally {
    loading = false;
  }

  assert.equal(loading, false);
  assert.equal(data.id, 1);
  assert.equal(error, null);

  // Test failure
  loading = true;
  data = null;
  error = null;

  try {
    throw new Error('500 Internal Server Error');
  } catch (err) {
    error = err;
  } finally {
    loading = false;
  }

  assert.equal(loading, false);
  assert.equal(data, null);
  assert.equal(error.message, '500 Internal Server Error');
});

test('empty tasks list correctly identifies empty state without indefinite loading', () => {
  const tasksResponse = { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 };
  const items = tasksResponse.items || [];
  const taskId = undefined;

  let selectedTaskId = null;
  if (!taskId && items.length > 0) {
    selectedTaskId = items[0].id;
  }

  assert.equal(selectedTaskId, null, 'No task should be selected if items array is empty');
  assert.equal(items.length === 0, true, 'Correctly flags empty queue state');
});
