const ist = new Intl.DateTimeFormat('en-IN', {
  dateStyle: 'medium', timeStyle: 'medium', timeZone: 'Asia/Kolkata',
});
export const formatIST = (value) => ist.format(new Date(value));

export function captureLocation(geolocation = globalThis.navigator?.geolocation) {
  if (!geolocation) return Promise.reject(new Error('Location capture is unavailable in this browser.'));
  return new Promise((resolve, reject) => {
    geolocation.getCurrentPosition(
      ({ coords, timestamp }) => {
        const captured = new Date(timestamp);
        if (![coords.latitude, coords.longitude, coords.accuracy].every(Number.isFinite)
            || Math.abs(coords.latitude) > 90 || Math.abs(coords.longitude) > 180 || coords.accuracy <= 0) {
          reject(new Error('The browser did not return a valid location. Try again.'));
          return;
        }
        resolve({
          latitude: coords.latitude,
          longitude: coords.longitude,
          accuracy_meters: coords.accuracy,
          ...(Number.isFinite(timestamp) && Number.isFinite(captured.getTime()) && { captured_at: captured.toISOString() }),
        });
      },
      ({ code }) => reject(new Error(code === 1
        ? 'Location permission was denied. Allow location for this site and try again.'
        : code === 3 ? 'Location capture timed out. Try again.' : 'Location is unavailable. Try again.')),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 },
    );
  });
}
