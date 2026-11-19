import assert from 'node:assert/strict';
import { test } from 'node:test';

const identity = { id: 'fictional-user', role: 'ADMIN', email: 'demo.admin@example.com' };
const json = (body, status = 200) => new Response(JSON.stringify(body), { status });

test('concurrent authenticated requests share a refresh and retry with the new access token', async (context) => {
  const api = await import('../src/services/api.js?test=refresh');
  const auth = api.API_ENDPOINTS.AUTH;
  const calls = [];
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push([url, options.headers.get('Authorization')]);
    if (url === auth.LOGIN) {
      assert.equal(options.credentials, 'include');
      return json({ access_token: 'synthetic-old' });
    }
    if (url === auth.REFRESH) {
      assert.equal(options.credentials, 'include');
      assert.equal(options.headers.get('X-CSRF-Protection'), '1');
      return json({ access_token: 'synthetic-new' });
    }
    if (url === auth.ME) return json(identity);
    assert.equal(options.credentials, 'omit');
    return options.headers.get('Authorization') === 'Bearer synthetic-old' ? json({}, 401) : json({ ok: true });
  });
  await api.signIn(identity.email, 'fictional password');
  assert.deepEqual(await Promise.all([api.apiClient('/example'), api.apiClient('/example')]), [
    { ok: true }, { ok: true },
  ]);
  assert.equal(calls.filter(([url]) => url === auth.REFRESH).length, 1);
  assert.equal(calls.filter(([url, token]) => url === '/example' && token === 'Bearer synthetic-new').length, 2);
  assert.deepEqual(api.getSession(), { state: 'authenticated', user: identity });
});

test('logout waits for restore to finish before clearing the session', async (context) => {
  const api = await import('../src/services/api.js?test=logout');
  const auth = api.API_ENDPOINTS.AUTH;
  const started = Promise.withResolvers();
  const release = Promise.withResolvers();
  const calls = [];
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    calls.push(url);
    if (url === auth.REFRESH) {
      started.resolve();
      await release.promise;
      return json({ access_token: 'synthetic-restored' });
    }
    if (url === auth.ME) return json(identity);
    assert.equal(url, auth.LOGOUT);
    assert.equal(options.credentials, 'include');
    assert.equal(options.headers.get('X-CSRF-Protection'), '1');
    return new Response(null, { status: 204 });
  });
  const restore = api.restoreSession();
  await started.promise;
  const logout = api.signOut();
  assert.deepEqual(calls, [auth.REFRESH]);
  release.resolve();
  await Promise.all([restore, logout]);
  assert.deepEqual(calls, [auth.REFRESH, auth.ME, auth.LOGOUT]);
  assert.deepEqual(api.getSession(), { state: 'anonymous', user: null });
  await assert.rejects(api.apiClient('/example'), { status: 401 });
});

test('multipart submissions delegate boundary generation and downloads return original bytes', async (context) => {
  const api = await import('../src/services/api.js?test=documents');
  const auth = api.API_ENDPOINTS.AUTH;
  const original = new Uint8Array([37, 80, 68, 70, 13, 10]);
  const body = new FormData();
  body.append('original_form', new Blob([original], { type: 'application/pdf' }), 'original.pdf');
  const endpoint = api.API_ENDPOINTS.APPLICATIONS.CREATE;
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    if (url === auth.LOGIN) return json({ access_token: 'synthetic' });
    if (url === auth.ME) return json(identity);
    assert.equal(options.headers.get('Authorization'), 'Bearer synthetic');
    if (url === endpoint) {
      assert.equal(options.body, body);
      assert.equal(options.headers.has('Content-Type'), false);
      return json({ id: 'fictional-application' }, 201);
    }
    assert.equal(options.headers.get('Accept'), '*/*');
    return new Response(original, { headers: { 'Content-Type': 'application/pdf' } });
  });
  await api.signIn(identity.email, 'fictional password');
  const app = await api.apiClient(endpoint, { method: 'POST', body });
  const blob = await api.apiClient(api.API_ENDPOINTS.APPLICATIONS.DOCUMENT(app.id, 'fictional-document'), {
    responseType: 'blob',
  });
  assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), original);
});

test('missing sessions, blocked checks and unavailable backends have different states', async (context) => {
  const cases = [
    ['missing', 401, 'anonymous'],
    ['blocked', 403, 'blocked'],
    ['proxy', 500, 'unavailable'],
    ['backend', 503, 'unavailable'],
    ['offline', null, 'unavailable'],
  ];
  for (const [name, status, state] of cases) {
    await context.test(name, async (subtest) => {
      const api = await import(`../src/services/api.js?test=restore-${name}`);
      const fetch = subtest.mock.method(globalThis, 'fetch', async (url, options) => {
        assert.equal(url, api.API_ENDPOINTS.AUTH.REFRESH);
        assert.equal(options.credentials, 'include');
        assert.equal(options.headers.get('X-CSRF-Protection'), '1');
        if (status === null) throw new TypeError('Failed to fetch');
        return json({}, status);
      });
      if (status === 401) assert.equal(await api.restoreSession(), null);
      else await assert.rejects(api.restoreSession());
      assert.deepEqual(api.getSession(), { state, user: null });
      assert.equal(fetch.mock.callCount(), 1);
    });
  }
});

test('a temporary /me failure after rotation can retry the check without rotating again', async (context) => {
  const api = await import('../src/services/api.js?test=identity-recovery');
  const auth = api.API_ENDPOINTS.AUTH;
  let identityStatus = 503;
  let refreshes = 0;
  context.mock.method(globalThis, 'fetch', async (url, options) => {
    if (url === auth.REFRESH) {
      refreshes++;
      return json({ access_token: 'synthetic-replacement' });
    }
    assert.equal(url, auth.ME);
    assert.equal(options.headers.get('Authorization'), 'Bearer synthetic-replacement');
    return identityStatus === 200 ? json(identity) : json({}, identityStatus);
  });
  await assert.rejects(api.restoreSession(), { status: 503 });
  assert.deepEqual(api.getSession(), { state: 'unavailable', user: null });
  identityStatus = 200;
  assert.deepEqual(await api.restoreSession(), identity);
  assert.equal(api.getSession().state, 'authenticated');
  identityStatus = 500;
  await assert.rejects(api.restoreSession(), { status: 500 });
  assert.equal(api.getSession().state, 'unavailable');
  identityStatus = 200;
  assert.deepEqual(await api.restoreSession(), identity);
  assert.equal(refreshes, 1);
});
