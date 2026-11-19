import React, { useState } from 'react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Input } from '../ui/Input';
import { Select } from '../ui/Select';
import { API_ENDPOINTS, apiClient } from '../../services/api';
import { captureLocation } from '../../services/location';
import { downloadODFile, evidenceOpen, odError, useODResource } from '../../services/od';

const states = {
  NOT_SUBMITTED: ['Evidence needed', 'neutral'],
  AWAITING_REVIEW: ['Awaiting verification', 'primary'],
  CORRECTION_REQUIRED: ['Correction requested', 'warning'],
  VERIFIED: ['Verified', 'success'],
  REJECTED: ['Rejected', 'danger'],
};
const decisions = [
  { value: 'APPROVED', label: 'Verify' },
  { value: 'REJECTED', label: 'Reject evidence' },
  { value: 'CORRECTION_REQUIRED', label: 'Request evidence correction' },
];
const reviewLabel = (status) => states[status === 'APPROVED' ? 'VERIFIED' : status]?.[0] ?? status;
const formatTime = (value) => new Date(value).toLocaleString();

function GPSDetails({ gps }) {
  return (
    <dl className="grid gap-2 text-xs sm:grid-cols-2">
      <div><dt className="text-brand-muted">Coordinates</dt><dd>{gps.latitude.toFixed(6)}, {gps.longitude.toFixed(6)}</dd></div>
      <div><dt className="text-brand-muted">Reported accuracy</dt><dd>{gps.accuracy_meters == null ? 'Unavailable' : `${gps.accuracy_meters} m`}</dd></div>
      <div><dt className="text-brand-muted">Device capture time</dt><dd>{formatTime(gps.captured_at)}</dd></div>
    </dl>
  );
}

function EvidenceForm({ applicationId, day, onSave }) {
  const [gps, setGPS] = useState(null);
  const [locating, setLocating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function locate() {
    setError('');
    setGPS(null);
    setLocating(true);
    try {
      setGPS(await captureLocation());
    } catch (failure) {
      setError(failure.message);
    } finally {
      setLocating(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (!gps) return;
    const fields = new FormData(event.currentTarget);
    const body = new FormData();
    body.append('details', JSON.stringify({ gps, notes: fields.get('notes'), submitted_at: new Date().toISOString() }));
    body.append('venue_photo', fields.get('venue_photo'));
    body.append('organizer_proof', fields.get('organizer_proof'));
    setError('');
    setSaving(true);
    try {
      await apiClient(API_ENDPOINTS.APPLICATIONS.SUBMIT_EVIDENCE(applicationId, day.id), { method: 'POST', body });
      onSave();
    } catch (failure) {
      setError(odError(failure, 'The evidence could not be saved.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="space-y-3 border-t border-brand-border pt-3" onSubmit={submit}>
      <Button variant="secondary" disabled={locating || saving} onClick={locate}>
        {locating ? 'Capturing location…' : gps ? 'Capture location again' : 'Capture location'}
      </Button>
      {gps && <GPSDetails gps={gps} />}
      <Input id={`venue-photo-${day.id}`} label="GPS Map Camera venue photo" type="file" name="venue_photo"
        accept=".png,.jpg,.jpeg" required />
      <Input id={`organizer-proof-${day.id}`} label="Organizer attendance proof" type="file" name="organizer_proof"
        accept=".pdf,.png,.jpg,.jpeg" required />
      <Input id={`evidence-notes-${day.id}`} label="Evidence notes (optional)" name="notes" maxLength={2000} />
      {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
      <Button type="submit" disabled={!gps || saving}>{saving ? 'Saving…' : 'Submit evidence'}</Button>
    </form>
  );
}

function EvidenceReviewForm({ applicationId, day, attempt, onSave }) {
  const [decision, setDecision] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function review(event) {
    event.preventDefault();
    const remarks = new FormData(event.currentTarget).get('remarks');
    setError('');
    setSaving(true);
    try {
      await apiClient(API_ENDPOINTS.TUTOR.REVIEW_EVIDENCE(applicationId, day.id, attempt.id), {
        method: 'POST', body: JSON.stringify({ review_status: decision, remarks }),
      });
      onSave();
    } catch (failure) {
      setError(odError(failure, 'The evidence review could not be saved.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="space-y-3 border-t border-brand-border pt-3" onSubmit={review}>
      <Select id={`evidence-decision-${day.id}`} label="Evidence decision" required options={decisions}
        value={decision} onChange={(event) => setDecision(event.target.value)} />
      <Input id={`evidence-remarks-${day.id}`} label="Evidence review remarks" name="remarks" maxLength={2000} required />
      {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
      <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save evidence review'}</Button>
    </form>
  );
}

function EvidenceAttempt({ attempt, applicationId }) {
  const [error, setError] = useState('');
  async function download(kind, file) {
    setError('');
    try {
      await downloadODFile(API_ENDPOINTS.APPLICATIONS.EVIDENCE_FILE(applicationId, attempt.id, kind), file.filename);
    } catch (failure) {
      setError(odError(failure, 'The evidence file could not be downloaded.'));
    }
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-brand-muted">Received {formatTime(attempt.server_received_at)}</p>
      {attempt.gps && <GPSDetails gps={attempt.gps} />}
      {attempt.notes && <p className="break-words text-sm">{attempt.notes}</p>}
      <div className="flex flex-wrap gap-2">
        {attempt.venue_photo && <Button size="sm" variant="secondary"
          onClick={() => download('venue-photo', attempt.venue_photo)}>Download venue photo</Button>}
        {attempt.organizer_proof && <Button size="sm" variant="secondary"
          onClick={() => download('organizer-proof', attempt.organizer_proof)}>Download organizer proof</Button>}
      </div>
      {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
      {attempt.reviews.map((review) => (
        <div key={review.reviewed_at} className="border-l-2 border-brand-border pl-2 text-sm">
          <p className="font-medium">{reviewLabel(review.review_status)}</p>
          <p className="text-xs text-brand-muted">{formatTime(review.reviewed_at)}</p>
          {review.remarks && <p className="break-words">{review.remarks}</p>}
        </div>
      ))}
    </div>
  );
}

export function EvidencePanel({ applicationId, tutor, onChange }) {
  const { data, error, reload } = useODResource(API_ENDPOINTS.APPLICATIONS.EVIDENCE(applicationId));
  if (error) return <p role="alert" className="text-sm text-rose-700">{error}</p>;
  if (!data) return <p role="status" className="text-sm">Loading evidence…</p>;
  if (data.status === 'REJECTED' && !data.days.some((day) => day.attempts.length)) return null;
  function saved() {
    reload();
    onChange();
  }
  return (
    <section aria-label="Participation evidence" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-brand-dark">Participation evidence</h2>
        <Button size="sm" variant="secondary" onClick={saved}>Refresh evidence</Button>
      </div>
      <p className="text-xs text-brand-muted">GPS and photo watermarks are supporting evidence and can be spoofed.</p>
      {data.days.some((day) => day.state === 'REJECTED') && (
        <p className="text-xs text-rose-700">A rejected event day prevents finalization.</p>
      )}
      {data.days.map((day) => {
        const latest = day.attempts.at(-1);
        const [label, variant] = states[day.state];
        return (
          <article key={day.id} aria-label={`Event day ${day.event_date}`}>
            <Card title={day.event_date} action={<Badge variant={variant}>{label}</Badge>} bodyClassName="space-y-3">
              {latest && <EvidenceAttempt key={`attempt-${latest.id}`} attempt={latest} applicationId={applicationId} />}
              {day.attempts.length > 1 && (
                <details className="space-y-2 text-sm">
                  <summary className="cursor-pointer">Earlier submissions ({day.attempts.length - 1})</summary>
                  {day.attempts.slice(0, -1).map((attempt) => (
                    <EvidenceAttempt key={attempt.id} attempt={attempt} applicationId={applicationId} />
                  ))}
                </details>
              )}
              {evidenceOpen.has(data.status) && !tutor && ['NOT_SUBMITTED', 'CORRECTION_REQUIRED'].includes(day.state) && (
                <EvidenceForm key={`upload-${latest?.id ?? day.id}`} applicationId={applicationId} day={day} onSave={saved} />
              )}
              {evidenceOpen.has(data.status) && tutor && day.state === 'AWAITING_REVIEW' && (
                <EvidenceReviewForm key={`review-${latest.id}`} applicationId={applicationId} day={day} attempt={latest} onSave={saved} />
              )}
            </Card>
          </article>
        );
      })}
    </section>
  );
}
