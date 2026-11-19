export function captureLocation(geolocation = globalThis.navigator?.geolocation) {
  if (!geolocation) return Promise.reject(new Error('Location capture is unavailable in this browser.'));
  return new Promise((resolve, reject) => {
    geolocation.getCurrentPosition(
      ({ coords, timestamp }) => {
        const captured = new Date(timestamp);
        if (![coords.latitude, coords.longitude, coords.accuracy, captured.getTime()].every(Number.isFinite)) {
          reject(new Error('The browser did not return a valid location. Try again.'));
          return;
        }
        resolve({
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracy_meters: coords.accuracy,
          captured_at: captured.toISOString(),
        });
      },
      ({ code }) => reject(new Error(code === 1
        ? 'Location permission was denied. Allow location for this site and try again.'
        : 'Location could not be captured. Try again.')),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 },
    );
  });
}
