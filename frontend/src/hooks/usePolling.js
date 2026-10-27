import { useEffect, useRef, useState, useCallback } from 'react';

/**
 * Custom hook to poll an async operation safely at a fixed interval.
 * Automatically cleans up on unmount or when disabled, and prevents overlapping requests.
 *
 * @param {Function} asyncFn - Async function returning data
 * @param {Object} options - Configuration options
 * @param {number} options.interval - Polling interval in ms (default 2000)
 * @param {boolean} options.enabled - Whether polling is active
 * @param {Function} options.onError - Optional error callback
 */
export function usePolling(asyncFn, { interval = 2000, enabled = true, onError } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(Boolean(enabled));
  const [error, setError] = useState(null);
  const isExecutingRef = useRef(false);
  const timerRef = useRef(null);
  const fnRef = useRef(asyncFn);
  const onErrorRef = useRef(onError);
  const isMountedRef = useRef(true);

  // Track component mount status
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  // Keep references fresh
  useEffect(() => {
    fnRef.current = asyncFn;
    onErrorRef.current = onError;
  }, [asyncFn, onError]);

  const execute = useCallback(async (isInitial = false) => {
    if (isExecutingRef.current) return;
    isExecutingRef.current = true;

    if (isInitial && isMountedRef.current) {
      setLoading(true);
    }

    try {
      const result = await fnRef.current();
      if (!isMountedRef.current) return;
      setData(result);
      setError(null);
    } catch (err) {
      if (!isMountedRef.current) return;
      setError(err);
      if (onErrorRef.current) {
        onErrorRef.current(err);
      }
    } finally {
      if (isMountedRef.current) {
        if (isInitial) setLoading(false);
        isExecutingRef.current = false;
      }
    }
  }, []);

  const refetch = useCallback((showLoading = false) => {
    return execute(showLoading);
  }, [execute]);

  useEffect(() => {
    if (!enabled) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setLoading(false);
      return;
    }

    // Immediate initial execution
    execute(true);

    timerRef.current = setInterval(() => {
      execute(false);
    }, interval);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [enabled, interval, execute]);

  return { data, loading, error, refetch, setData, setLoading };
}

export default usePolling;
