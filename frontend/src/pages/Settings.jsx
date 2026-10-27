import React, { useState, useEffect } from 'react';
import {
  Settings as SettingsIcon,
  Server,
  Database,
  Cpu,
  ShieldCheck,
  Send,
  Loader2,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
} from 'lucide-react';
import { api } from '../api/client';

export function Settings() {
  const [health, setHealth] = useState(null);
  const [llmStatus, setLlmStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // LLM Test form
  const [testPrompt, setTestPrompt] = useState('Write a Python function to compute Fibonacci numbers.');
  const [testingLlm, setTestingLlm] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState(null);
  const [llmTestError, setLlmTestError] = useState(null);

  const fetchSettingsData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [healthRes, llmRes] = await Promise.allSettled([
        api.getHealth(),
        api.getLlmStatus(),
      ]);

      if (healthRes.status === 'fulfilled') {
        setHealth(healthRes.value);
      }
      if (llmRes.status === 'fulfilled') {
        setLlmStatus(llmRes.value);
      }
    } catch (err) {
      setError(err.message || 'Failed to fetch engine configuration.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSettingsData();
  }, []);

  const handleTestLlm = async (e) => {
    e.preventDefault();
    if (!testPrompt.trim()) return;

    setTestingLlm(true);
    setLlmTestResult(null);
    setLlmTestError(null);

    try {
      const res = await api.testLlm(testPrompt.trim());
      setLlmTestResult(res);
    } catch (err) {
      setLlmTestError(err.message || 'LLM execution test failed.');
    } finally {
      setTestingLlm(false);
    }
  };

  const apiUrl = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', maxWidth: '960px' }}>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--text-primary)' }}>
            System Settings & Engine Diagnostics
          </h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Inspect connection health, database status, and LLM orchestration settings.
          </p>
        </div>

        <button
          type="button"
          className="btn btn-secondary btn-sm"
          onClick={fetchSettingsData}
          disabled={loading}
        >
          <RefreshCw size={13} className={loading ? 'spin-animation' : ''} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Security Assurance Banner */}
      <div
        style={{
          padding: '0.9rem 1.25rem',
          backgroundColor: 'var(--bg-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
        }}
      >
        <ShieldCheck size={20} color="var(--accent-blue)" />
        <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
          <strong style={{ color: 'var(--text-primary)' }}>Strict Security Policy:</strong> API tokens
          (GitHub Token, Groq API Key) are strictly encapsulated on the backend and are never returned or
          exposed in API responses or frontend client states.
        </div>
      </div>

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

      {/* Configuration Cards Grid */}
      <div className="grid-2">
        {/* Backend API & Database Card */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">
              <Server size={18} color="var(--accent-blue)" />
              <span>Backend & Database</span>
            </h3>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.82rem' }}>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                API Server URL (VITE_API_URL)
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {apiUrl}
              </div>
            </div>

            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                System Health Status
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '2px' }}>
                <span className={`status-dot ${health?.status === 'healthy' ? 'healthy' : 'degraded'}`} />
                <span style={{ textTransform: 'capitalize', fontWeight: 600 }}>
                  {health?.status || 'Unknown'}
                </span>
              </div>
            </div>

            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                Database Reachability
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--status-success)' }}>
                {health?.database === 'connected' ? 'Connected (PostgreSQL)' : health?.database || 'Checking...'}
              </div>
            </div>
          </div>
        </div>

        {/* LLM Engine Card */}
        <div className="card">
          <div className="card-header">
            <h3 className="card-title">
              <Cpu size={18} color="var(--accent-violet)" />
              <span>LLM Orchestration</span>
            </h3>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', fontSize: '0.82rem' }}>
            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                Provider
              </div>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                {llmStatus?.provider || 'Groq Cloud'}
              </div>
            </div>

            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                Configured Model Identifier
              </div>
              <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)' }}>
                {llmStatus?.model || 'openai/gpt-oss-120b'}
              </div>
            </div>

            <div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                Credentials Status
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginTop: '2px' }}>
                {llmStatus?.configured ? (
                  <>
                    <CheckCircle2 size={14} color="var(--status-success)" />
                    <span style={{ color: 'var(--status-success)', fontWeight: 600 }}>
                      Configured & Validated
                    </span>
                  </>
                ) : (
                  <>
                    <AlertCircle size={14} color="var(--status-warning)" />
                    <span style={{ color: 'var(--status-warning)', fontWeight: 600 }}>
                      Unconfigured (Check GROQ_API_KEY)
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Real LLM Execution Test Console */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3 className="card-title">Test LLM Inference Endpoint</h3>
            <div className="card-subtitle">
              Verify live model completion latency and responses without exposing credentials
            </div>
          </div>
        </div>

        <form onSubmit={handleTestLlm} style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          <textarea
            className="form-textarea"
            style={{ minHeight: '80px', fontFamily: 'var(--font-mono)', fontSize: '0.82rem' }}
            placeholder="Enter test prompt..."
            value={testPrompt}
            onChange={(e) => setTestPrompt(e.target.value)}
            disabled={testingLlm}
          />

          <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
            <button
              type="submit"
              className="btn btn-primary btn-sm"
              disabled={testingLlm || !testPrompt.trim()}
            >
              {testingLlm ? (
                <>
                  <Loader2 size={14} className="spin-animation" />
                  <span>Invoking Model...</span>
                </>
              ) : (
                <>
                  <Send size={14} />
                  <span>Execute Test</span>
                </>
              )}
            </button>
          </div>
        </form>

        {llmTestError && (
          <div
            style={{
              marginTop: '0.75rem',
              padding: '0.75rem 1rem',
              backgroundColor: 'var(--status-error-bg)',
              border: '1px solid var(--status-error-border)',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--status-error)',
              fontSize: '0.8rem',
            }}
          >
            {llmTestError}
          </div>
        )}

        {llmTestResult && (
          <div
            style={{
              marginTop: '0.9rem',
              backgroundColor: '#070B12',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)',
              padding: '1rem',
            }}
          >
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: '0.75rem',
                color: 'var(--text-muted)',
                marginBottom: '0.5rem',
                borderBottom: '1px solid var(--border-subtle)',
                paddingBottom: '0.4rem',
              }}
            >
              <span>Model: {llmTestResult.model}</span>
              {llmTestResult.latency_ms && <span>Latency: {llmTestResult.latency_ms} ms</span>}
            </div>
            <pre
              style={{
                margin: 0,
                fontFamily: 'var(--font-mono)',
                fontSize: '0.8rem',
                color: '#E2E8F0',
                whiteSpace: 'pre-wrap',
                lineHeight: 1.5,
              }}
            >
              {llmTestResult.response}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}

export default Settings;
