/**
 * Centralized API configuration for Campus OD.
 * Sri Krishna Arts and Science College (SKASC)
 *
 * Access credentials stay in memory. The browser owns the refresh cookie.
 */

const API_BASE_URL = '/api/v1';

export const API_ENDPOINTS = {
  HEALTH: `${API_BASE_URL}/health/db`,
  STATUS: `${API_BASE_URL}/status`,
  AUTH: {
    LOGIN: `${API_BASE_URL}/auth/login`,
    LOGOUT: `${API_BASE_URL}/auth/logout`,
    ME: `${API_BASE_URL}/auth/me`,
    REFRESH: `${API_BASE_URL}/auth/refresh`,
    ACTIVATE: `${API_BASE_URL}/auth/activate`,
  },
  APPLICATIONS: {
    LIST: `${API_BASE_URL}/applications`,
    CREATE: `${API_BASE_URL}/applications`,
    DETAIL: (id) => `${API_BASE_URL}/applications/${id}`,
    RESUBMIT: (id) => `${API_BASE_URL}/applications/${id}/resubmit`,
    DOCUMENT: (id, documentId) => `${API_BASE_URL}/applications/${id}/documents/${documentId}`,
    EVIDENCE: (id) => `${API_BASE_URL}/applications/${id}/evidence`,
    SUBMIT_EVIDENCE: (id, day) => `${API_BASE_URL}/applications/${id}/days/${day}/evidence`,
    EVIDENCE_FILE: (id, submission, kind) => `${API_BASE_URL}/applications/${id}/evidence/${submission}/files/${kind}`,
  },
  TUTOR: {
    APPLICATIONS: `${API_BASE_URL}/tutor/applications`,
    DECISION: (id) => `${API_BASE_URL}/tutor/applications/${id}/decision`,
    REVIEW_EVIDENCE: (id, day, submission) => `${API_BASE_URL}/tutor/applications/${id}/days/${day}/evidence/${submission}/review`,
  },
  ADMIN: {
    USERS: `${API_BASE_URL}/admin/users`,
    METRICS: `${API_BASE_URL}/admin/metrics`,
    DEMO_ROSTER: `${API_BASE_URL}/admin/demo-roster`,
    STUDENTS: `${API_BASE_URL}/admin/students`,
    TUTORS: `${API_BASE_URL}/admin/tutors`,
    ACADEMICS: `${API_BASE_URL}/admin/academics`,
    ASSIGN_TUTOR: (id) => `${API_BASE_URL}/admin/academics/classes/${id}/tutor`,
  },
};

let accessToken = null;
let snapshot = { state: 'loading', user: null };
let cookieQueue = Promise.resolve();
let refreshInFlight = null;
const subscribers = new Set();
const authChannel = typeof window !== 'undefined' && 'BroadcastChannel' in window
  ? new BroadcastChannel('campus-od-session')
  : null;

export const portalPaths = {
  STUDENT: '/student/dashboard',
  TUTOR: '/tutor/dashboard',
  ADMIN: '/admin/dashboard',
};

export const getSession = () => snapshot;
export function subscribeSession(listener) {
  subscribers.add(listener);
  return () => subscribers.delete(listener);
}

function setSession(state, user = null, token = null) {
  accessToken = token;
  snapshot = { state, user };
  for (const listener of subscribers) listener();
}

function setSessionCheckFailure(error, token) {
  setSession(error.status === 403 ? 'blocked' : 'unavailable', null, token);
}

if (authChannel) {
  authChannel.onmessage = ({ data }) => {
    if (data === 'session-changed') setSession('anonymous');
  };
}

function serializeCookies(operation) {
  const result = cookieQueue.then(() => {
    const locks = globalThis.navigator?.locks;
    return locks ? locks.request('campus-od-refresh-cookie', operation) : operation();
  });
  cookieQueue = result.catch(() => {});
  return result;
}

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(endpoint, options = {}, { token = null, cookies = false, csrf = false } = {}) {
  const { responseType, ...fetchOptions } = options;
  const headers = new Headers(options.headers);
  headers.set('Accept', responseType === 'blob' ? '*/*' : 'application/json');
  if (typeof options.body === 'string') headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (csrf) headers.set('X-CSRF-Protection', '1');
  const response = await fetch(endpoint, {
    ...fetchOptions, headers, credentials: cookies ? 'include' : 'omit', cache: 'no-store',
    mode: 'same-origin', redirect: 'error',
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(response.status, typeof data.detail === 'string' ? data.detail : 'Request failed.');
  }
  if (responseType === 'blob') return response.blob();
  return response.status === 204 ? null : response.json();
}

async function loadIdentity(token) {
  const user = await request(API_ENDPOINTS.AUTH.ME, {}, { token });
  if (!Object.hasOwn(portalPaths, user.role)) throw new Error('This account has no portal access.');
  return user;
}

function refreshSession(previousToken = accessToken) {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = serializeCookies(async () => {
    if (accessToken && accessToken !== previousToken) return snapshot.user;
    if (previousToken && !accessToken) return null;
    let token = null;
    try {
      const session = await request(API_ENDPOINTS.AUTH.REFRESH, { method: 'POST' }, { cookies: true, csrf: true });
      token = session.access_token;
      const user = await loadIdentity(token);
      setSession('authenticated', user, token);
      return user;
    } catch (error) {
      if (error.status === 401) {
        setSession('anonymous');
        return null;
      }
      setSessionCheckFailure(error, token);
      throw error;
    }
  }).finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

export async function restoreSession() {
  const token = accessToken;
  if (!token) return refreshSession();
  try {
    const user = await loadIdentity(token);
    if (token === accessToken) setSession('authenticated', user, token);
    return user;
  } catch (error) {
    if (token === accessToken) {
      if (error.status === 401) return refreshSession(token);
      setSessionCheckFailure(error, token);
    }
    throw error;
  }
}

export function signIn(email, password) {
  return serializeCookies(async () => {
    const session = await request(API_ENDPOINTS.AUTH.LOGIN, {
      method: 'POST', body: JSON.stringify({ email, password }),
    }, { cookies: true });
    try {
      const user = await loadIdentity(session.access_token);
      setSession('authenticated', user, session.access_token);
      return user;
    } catch (error) {
      if (error.status === 401) setSession('anonymous');
      else setSessionCheckFailure(error, session.access_token);
      throw error;
    } finally {
      authChannel?.postMessage('session-changed');
    }
  });
}

export function signOut() {
  return serializeCookies(async () => {
    await request(API_ENDPOINTS.AUTH.LOGOUT, { method: 'POST' }, { cookies: true, csrf: true });
    setSession('anonymous');
    authChannel?.postMessage('session-changed');
  });
}

export function activateAccount(invitation, password) {
  return request(API_ENDPOINTS.AUTH.ACTIVATE, {
    method: 'POST', body: JSON.stringify({ invitation, password }),
  }, { csrf: true });
}

export async function apiClient(endpoint, options = {}) {
  const token = accessToken;
  const userId = snapshot.user?.id;
  if (!token) throw new ApiError(401, 'Sign in again.');
  try {
    return await request(endpoint, options, { token, csrf: true });
  } catch (error) {
    if (error.status !== 401) throw error;
    const user = await refreshSession(token);
    // A different account may have signed in while this request was in flight.
    if (!user || user.id !== userId) throw error;
    return request(endpoint, options, { token: accessToken, csrf: true });
  }
}
