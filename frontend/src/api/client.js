/**
 * Centralized API client for CodeForge AI.
 * Communicates with FastAPI backend using VITE_API_URL and standard fetch.
 */

const API_BASE_URL = (
  (typeof import.meta !== 'undefined' && import.meta.env?.VITE_API_URL) ||
  'http://localhost:8000'
).replace(/\/+$/, '');

/**
 * Safely extracts human-readable error messages from API response bodies,
 * including FastAPI validation error arrays, HTTP exceptions, and network errors.
 * Never produces `[object Object]`.
 */
export function formatApiErrorMessage(data, status = 0) {
  if (!data) {
    return status ? `Request failed with status ${status}` : 'Unknown error occurred';
  }

  // If already a string
  if (typeof data === 'string') {
    return data;
  }

  // Check detail property (FastAPI convention)
  if (data.detail !== undefined && data.detail !== null) {
    // Array of Pydantic validation errors: [{ loc: [...], msg: "...", type: "..." }]
    if (Array.isArray(data.detail)) {
      const messages = data.detail.map((item) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') {
          const field = Array.isArray(item.loc)
            ? item.loc.filter((part) => part !== 'body').join('.')
            : '';
          const rawMsg = item.msg || item.message || JSON.stringify(item);
          const cleanMsg = String(rawMsg).replace(/^Value error,\s*/i, '');
          return field ? `${field}: ${cleanMsg}` : cleanMsg;
        }
        return String(item);
      });
      return messages.filter(Boolean).join('; ') || `Validation error (${status})`;
    }

    if (typeof data.detail === 'string') {
      return data.detail;
    }

    if (typeof data.detail === 'object') {
      return formatApiErrorMessage(data.detail, status);
    }
  }

  // Check message property
  if (typeof data.message === 'string') {
    return data.message;
  }

  // Check error property
  if (data.error !== undefined && data.error !== null) {
    if (typeof data.error === 'string') return data.error;
    if (typeof data.error === 'object') return formatApiErrorMessage(data.error, status);
  }

  // Fallback for unexpected objects
  try {
    const jsonStr = JSON.stringify(data);
    if (jsonStr !== '{}' && jsonStr !== '[]') {
      return jsonStr;
    }
  } catch {
    // ignore json serialization errors
  }

  return status ? `Request failed with status ${status}` : 'An unexpected error occurred';
}

/**
 * Safely extracts error text from an Error, ApiError, string, or arbitrary object.
 */
export function getErrorMessage(err) {
  if (!err) return '';
  if (typeof err === 'string') return err;
  if (err instanceof ApiError) return err.message;
  if (err.message && typeof err.message === 'string') return err.message;
  return formatApiErrorMessage(err);
}

export class ApiError extends Error {
  constructor(message, status, details = null) {
    const safeMessage = typeof message === 'string' ? message : formatApiErrorMessage(message, status);
    super(safeMessage);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

/**
 * Standard fetch wrapper with JSON serialization, timeout, and typed error handling.
 */
async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;
  const headers = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
    ...options.headers,
  };

  const config = {
    ...options,
    headers,
  };

  try {
    const response = await fetch(url, config);

    if (response.status === 204) {
      return null;
    }

    let data;
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      data = await response.json();
    } else {
      data = await response.text();
    }

    if (!response.ok) {
      const errorMessage = formatApiErrorMessage(data, response.status);
      throw new ApiError(errorMessage, response.status, data);
    }

    return data;
  } catch (err) {
    if (err instanceof ApiError) {
      throw err;
    }
    // Network errors, connection refused, or timeouts
    throw new ApiError(
      err.message || 'Unable to connect to CodeForge API server. Please check your backend connection.',
      0,
      { originalError: err.message }
    );
  }
}

export const api = {
  // System Endpoints
  async getHealth() {
    return request('/health');
  },

  async getLlmStatus() {
    return request('/llm/status');
  },

  async testLlm(prompt, systemPrompt = '') {
    return request('/llm/test', {
      method: 'POST',
      body: JSON.stringify({ prompt, system_prompt: systemPrompt }),
    });
  },

  // GitHub Endpoints
  async validateRepository(repositoryUrl) {
    return request('/github/validate-repository', {
      method: 'POST',
      body: JSON.stringify({ repository_url: repositoryUrl }),
    });
  },

  async inspectRepository(repositoryUrl) {
    return request('/github/repositories/inspect', {
      method: 'POST',
      body: JSON.stringify({ repository_url: repositoryUrl }),
    });
  },

  async getIssues(repository, state = 'open') {
    const params = new URLSearchParams({ repository, state });
    return request(`/github/issues?${params.toString()}`);
  },

  async getIssue(owner, repo, issueNumber) {
    return request(`/github/issues/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${issueNumber}`);
  },

  // Task Endpoints
  async createTask(payload) {
    return request('/tasks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async listTasks({ page = 1, pageSize = 20, status = null } = {}) {
    const params = new URLSearchParams();
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
    if (status) {
      params.set('status', status);
    }
    return request(`/tasks?${params.toString()}`);
  },

  async getTask(taskId) {
    return request(`/tasks/${taskId}`);
  },

  async getTaskState(taskId) {
    return request(`/tasks/${taskId}/state`);
  },

  async getTaskEvents(taskId) {
    return request(`/tasks/${taskId}/events`);
  },

  async getTaskChanges(taskId) {
    return request(`/tasks/${taskId}/changes`);
  },

  async getTaskTests(taskId) {
    return request(`/tasks/${taskId}/tests`);
  },

  async retryTask(taskId) {
    return request(`/tasks/${taskId}/retry`, {
      method: 'POST',
    });
  },

  async cancelTask(taskId) {
    return request(`/tasks/${taskId}/cancel`, {
      method: 'POST',
    });
  },

  // Pull Request Endpoints
  async getTaskPrPreview(taskId) {
    return request(`/tasks/${taskId}/pr`);
  },

  async approveTaskPr(taskId, comment = null) {
    return request(`/tasks/${taskId}/pr/approve`, {
      method: 'POST',
      body: JSON.stringify({ approved: true, comment }),
    });
  },

  async createTaskPr(taskId, { approved = true, title = null, body = null, base_branch = null, draft = false } = {}) {
    return request(`/tasks/${taskId}/pr/create`, {
      method: 'POST',
      body: JSON.stringify({
        approved,
        title,
        body,
        base_branch,
        draft,
      }),
    });
  },

  async createGitHubPullRequest(payload) {
    return request('/github/pull-requests', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  async getGitHubPullRequest(owner, repo, prNumber) {
    return request(`/github/pull-requests/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/${prNumber}`);
  },
};

export default api;
