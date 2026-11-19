import assert from 'node:assert/strict';
import { test } from 'node:test';
import { captureLocation } from '../src/services/location.js';

test('location permission denial returns a clear error and no coordinates', async () => {
  const browser = { getCurrentPosition(_success, error) { error({ code: 1 }); } };
  await assert.rejects(captureLocation(browser), /Location permission was denied/);
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
