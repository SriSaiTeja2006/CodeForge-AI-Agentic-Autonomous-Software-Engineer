import test from 'node:test';
import assert from 'node:assert/strict';
import { formatApiErrorMessage, getErrorMessage, ApiError } from '../src/api/client.js';

test('formatApiErrorMessage handles FastAPI 422 validation error arrays', () => {
  const fastapi422 = {
    detail: [
      {
        type: 'value_error',
        loc: ['body', 'repository_url'],
        msg: 'Value error, Invalid repository URL. Must be a valid GitHub repository URL: Invalid URL',
        input: 'https://invalid-url.com',
      },
    ],
  };

  const formatted = formatApiErrorMessage(fastapi422, 422);
  assert.equal(
    formatted,
    'repository_url: Invalid repository URL. Must be a valid GitHub repository URL: Invalid URL'
  );
  assert.ok(!formatted.includes('[object Object]'));
});

test('formatApiErrorMessage handles multiple validation errors', () => {
  const multiError = {
    detail: [
      { loc: ['body', 'repository_url'], msg: 'repository_url cannot be empty' },
      { loc: ['body', 'task_description'], msg: 'task_description cannot be empty' },
    ],
  };

  const formatted = formatApiErrorMessage(multiError, 422);
  assert.equal(
    formatted,
    'repository_url: repository_url cannot be empty; task_description: task_description cannot be empty'
  );
  assert.ok(!formatted.includes('[object Object]'));
});

test('formatApiErrorMessage handles FastAPI HTTPException string detail', () => {
  const httpException = { detail: 'Repository not found on GitHub or private.' };
  const formatted = formatApiErrorMessage(httpException, 404);
  assert.equal(formatted, 'Repository not found on GitHub or private.');
});

test('formatApiErrorMessage handles generic error message object', () => {
  const errObj = { message: 'Network connection lost' };
  const formatted = formatApiErrorMessage(errObj, 500);
  assert.equal(formatted, 'Network connection lost');
});

test('formatApiErrorMessage handles plain string or empty responses', () => {
  assert.equal(formatApiErrorMessage('Bad Gateway', 502), 'Bad Gateway');
  assert.equal(formatApiErrorMessage(null, 500), 'Request failed with status 500');
  assert.equal(formatApiErrorMessage(undefined, 0), 'Unknown error occurred');
});

test('getErrorMessage safely extracts text from ApiError, Error, string, and raw objects', () => {
  const apiErr = new ApiError('Custom API error', 400);
  assert.equal(getErrorMessage(apiErr), 'Custom API error');

  const standardErr = new Error('Standard JS error');
  assert.equal(getErrorMessage(standardErr), 'Standard JS error');

  const str = 'Plain string error';
  assert.equal(getErrorMessage(str), 'Plain string error');

  const validationObj = {
    detail: [{ loc: ['body', 'issue_number'], msg: 'Input should be a valid integer' }],
  };
  const extracted = getErrorMessage(validationObj);
  assert.equal(extracted, 'issue_number: Input should be a valid integer');
  assert.ok(!extracted.includes('[object Object]'));
});

test('Never returns [object Object] for unexpected payloads', () => {
  const weirdObj = { somethingUnexpected: 123, sub: { key: 'val' } };
  const formatted = formatApiErrorMessage(weirdObj, 400);
  assert.ok(!formatted.includes('[object Object]'));
  assert.ok(formatted.includes('somethingUnexpected'));
});
