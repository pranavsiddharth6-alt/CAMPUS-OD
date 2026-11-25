import React, { useState } from 'react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Select } from '../ui/Select';
import { API_ENDPOINTS, apiClient } from '../../services/api';
import { captureLocation, formatIST } from '../../services/location';
import { odError, useODResource } from '../../services/od';
import { VenueMap } from './VenueMap';

const outcomes = {
  PASSED: 'Location check passed',
  OUTSIDE_BOUNDARY: 'Outside the allowed venue boundary',
  POOR_ACCURACY: 'Reported GPS accuracy exceeds the threshold',
  OUTSIDE_AND_POOR_ACCURACY: 'Outside the allowed boundary and poor GPS accuracy',
};

const metres = (value) => new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1 }).format(value) + ' m';

function CaptureResult({ capture }) {
  return (
    <div className="space-y-2">
      <Badge variant={capture.result === 'PASSED' ? 'success' : 'warning'}>{outcomes[capture.result]}</Badge>
      <dl className="grid gap-2 text-sm sm:grid-cols-2">
        <div><dt>Distance from venue</dt><dd>{metres(capture.distance_metres)} · limit {metres(capture.allowed_radius_metres)}</dd></div>
        <div><dt>Reported accuracy</dt><dd>{metres(capture.accuracy_meters)} · limit {metres(capture.allowed_accuracy_metres)}</dd></div>
        <div><dt>Server received (IST)</dt><dd>{formatIST(capture.server_recorded_at)}</dd></div>
        <div><dt>Device capture time (IST)</dt><dd>{capture.captured_at ? formatIST(capture.captured_at) : 'Unavailable'}</dd></div>
        <div><dt>Coordinates</dt><dd>{capture.latitude.toFixed(6)}, {capture.longitude.toFixed(6)}</dd></div>
      </dl>
      {capture.result !== 'PASSED' && <p className="text-sm text-brand-muted">This attempt is saved and flagged for Faculty review.</p>}
    </div>
  );
}

export function MapODPanel({ applicationId, readOnly = false }) {
  const { data, error, reload } = useODResource(API_ENDPOINTS.APPLICATIONS.MAP_OD(applicationId));
  const [updated, setUpdated] = useState(null);
  const [dayId, setDayId] = useState('');
  const [attemptId, setAttemptId] = useState('');
  const [busy, setBusy] = useState(false);
  const [captureError, setCaptureError] = useState('');
  const [pending, setPending] = useState(null);
  const response = updated ?? data;
  const day = response?.days.find(({ id }) => id === dayId)
    ?? response?.days.find(({ can_capture }) => can_capture) ?? response?.days[0];
  const selected = day?.attempts.find(({ id }) => id === day.selected_capture_id);
  const capture = day?.attempts.find(({ id }) => id === attemptId) ?? selected;
  const radius = capture?.allowed_radius_metres ?? response?.radius_metres;

  async function captureOrRetry(retry) {
    setBusy(true);
    setCaptureError('');
    try {
      const payload = retry ? pending.payload : { ...await captureLocation(), request_id: crypto.randomUUID() };
      setPending({ day: day.id, payload });
      const result = await apiClient(API_ENDPOINTS.APPLICATIONS.CAPTURE_LOCATION(applicationId, day.id), {
        method: 'POST', body: JSON.stringify(payload),
      });
      setUpdated(result);
      setAttemptId(result.received_capture_id);
      setPending(null);
    } catch (failure) {
      if (failure.status && failure.status < 500) setPending(null);
      setCaptureError(odError(failure, failure.message || 'The capture could not be saved.'));
    } finally {
      setBusy(false);
    }
  }

  if (!response) return error ? (
    <div className="space-y-2"><p role="alert">{error}</p><Button variant="secondary" onClick={reload}>Try again</Button></div>
  ) : <p role="status" className="text-sm">Loading Map OD…</p>;

  return (
    <Card title="Map OD" bodyClassName="space-y-4">
      <p className="text-sm"><span className="font-semibold">Expected event venue</span> · {response.venue_name}</p>
      {!response.expected_venue ? <p className="text-sm text-brand-muted">This legacy application has no venue pin. Its existing evidence is available without a geographic verification result.</p> : <>
        <p className="text-sm">{response.expected_venue.latitude.toFixed(6)}, {response.expected_venue.longitude.toFixed(6)}</p>
        <ul className="grid gap-2 text-sm sm:grid-cols-2" aria-label="Event day capture progress">
          {response.days.map((row) => {
            const result = row.attempts.find(({ id }) => id === row.selected_capture_id)?.result;
            return <li key={row.id} className="rounded border border-brand-border p-2">{row.event_date} · {result === 'PASSED'
              ? 'Location check passed' : result ? 'Flagged for review' : 'Location not captured'}</li>;
          })}
        </ul>
        <Select label="Event day" options={response.days.map((row) => ({ value: row.id, label: row.event_date }))}
          value={day?.id ?? ''} disabled={busy} onChange={(event) => {
            setDayId(event.target.value);
            setAttemptId('');
            setCaptureError('');
          }} />
        <VenueMap venue={response.expected_venue} capture={capture} radius={radius} />
        <p className="text-sm">Boundary radius · {metres(radius)}</p>
        {capture && <CaptureResult capture={capture} />}
        {selected && <p className="text-sm text-brand-muted">{capture?.id === selected.id
          ? 'Showing the selected capture for this event day.' : 'Showing a different attempt. The selected capture is marked below.'}</p>}
        {day?.attempts.length > 0 && <details>
          <summary className="cursor-pointer text-sm">Capture history ({day.attempts.length})</summary>
          <ul className="mt-2 space-y-2">
            {[...day.attempts].reverse().map((row) => <li key={row.id} className="text-sm">
              <button type="button" className="text-brand-primary underline" onClick={() => setAttemptId(row.id)}>
                {formatIST(row.server_recorded_at)} · {outcomes[row.result]}
              </button>
              {row.id === day.selected_capture_id && ' · Selected'}
              {row.id === day.attached_capture_id && ' · Attached to file evidence'}
            </li>)}
          </ul>
        </details>}
        {!readOnly && <>
          <p className="text-sm text-brand-muted">Capture is available on the selected event date in IST ({response.today_ist} today).</p>
          {captureError && <p role="alert" className="text-sm text-rose-700">{captureError}</p>}
          <div className="flex flex-wrap gap-2">
            <Button disabled={!day?.can_capture || busy} onClick={() => captureOrRetry(false)}>
              {busy ? 'Capturing or saving…' : day?.attempts.length ? 'Capture location again' : 'Capture location'}
            </Button>
            {pending?.day === day?.id && <Button variant="secondary" disabled={!day?.can_capture || busy}
              onClick={() => captureOrRetry(true)}>Retry saving capture</Button>}
            <Button variant="secondary" disabled={busy} onClick={() => { setUpdated(null); reload(); }}>Refresh</Button>
          </div>
        </>}
        <p className="text-sm text-brand-muted">Browser GPS can be inaccurate or spoofed. Faculty still review participation evidence.</p>
      </>}
    </Card>
  );
}
