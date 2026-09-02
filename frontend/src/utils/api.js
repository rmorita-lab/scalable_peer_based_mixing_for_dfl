const getApiBase = () => {
  if (process.env.REACT_APP_API_BASE) {
    return process.env.REACT_APP_API_BASE;
  }
  if (typeof window !== 'undefined' && window.location && window.location.hostname) {
    return `http://${window.location.hostname}:8000`;
  }
  return 'http://localhost:8000';
};

export const API_BASE = getApiBase();

export const MAX_METRICS = 100000;

export async function fetchMetricsHistory(offset = 0, limit = 50000) {
  const response = await fetch(`${API_BASE}/metrics/history?offset=${offset}&limit=${limit}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch metrics history: ${response.status}`);
  }
  return response.json();
}
