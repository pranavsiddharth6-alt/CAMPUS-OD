import assert from 'node:assert/strict';
import { test } from 'node:test';
import { captureLocation, formatIST } from '../src/services/location.js';

test('location permission denial returns a clear error and no coordinates', async () => {
  const browser = { getCurrentPosition(_success, error) { error({ code: 1 }); } };
  await assert.rejects(captureLocation(browser), /Location permission was denied/);
});

test('location timeout and unavailable readings do not produce a location', async () => {
  await assert.rejects(captureLocation({ getCurrentPosition(_success, error) { error({ code: 3 }); } }), /timed out/);
  await assert.rejects(captureLocation({ getCurrentPosition(_success, error) { error({ code: 2 }); } }), /unavailable/);
});

test('capture accepts missing client time and rejects structurally invalid position data', async () => {
  const browser = (accuracy) => ({
    getCurrentPosition(success) { success({ coords: { latitude: 1, longitude: 2, accuracy } }); },
  });
  assert.deepEqual(await captureLocation(browser(30)), { latitude: 1, longitude: 2, accuracy_meters: 30 });
  await assert.rejects(captureLocation(browser(0)), /valid location/);
  await assert.rejects(captureLocation(browser(Infinity)), /valid location/);
});

test('capture times display in IST across UTC rollover', () => {
  assert.match(formatIST('2026-11-19T18:30:00Z'), /20 Nov 2026/);
});

test('capture preserves the readings, reported accuracy and browser timestamp', async () => {
  const browser = {
    getCurrentPosition(success, _error, options) {
      assert.equal(options.maximumAge, 0);
      success({ coords: { latitude: 1.25, longitude: -2.5, accuracy: 15.75 }, timestamp: 0 });
    },
  };
  assert.deepEqual(await captureLocation(browser), {
    latitude: 1.25, longitude: -2.5, accuracy_meters: 15.75, captured_at: '1970-01-01T00:00:00.000Z',
  });
});
