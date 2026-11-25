import React, { useRef, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { Download } from 'lucide-react';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { EvidencePanel } from '../components/od/EvidencePanel';
import { VenueMap } from '../components/od/VenueMap';
import { MapODPanel } from '../components/od/MapODPanel';
import { API_ENDPOINTS, apiClient } from '../services/api';
import { correctionRequested, downloadODFile, evidenceOpen, odError, reviewable, statusLabel, statusVariant, useODResource, viewODFile } from '../services/od';

const documentLabels = {
  ORIGINAL_SIGNED_OD_FORM: 'Original signed OD form',
  EVENT_INVITATION: 'Event invitation',
  PARENT_CONSENT: 'Parent consent',
};
const decisions = [
  { value: 'PREAPPROVE', label: 'Approve Prior OD' },
  { value: 'REJECT', label: 'Reject' },
  { value: 'REQUEST_CORRECTION', label: 'Request correction' },
];

const hodDecisions = [{ value: 'APPROVE', label: 'Approve and finalize OD' }, ...decisions.slice(1)];

export function ApplicationDetailPage({ tutor = false, hod = false, admin = false, priorMonitor = false }) {
  const { applicationId } = useParams();
  const endpoint = priorMonitor ? API_ENDPOINTS.HOD.PRIOR(applicationId)
    : admin ? API_ENDPOINTS.ADMIN.APPLICATION(applicationId) : API_ENDPOINTS.APPLICATIONS.DETAIL(applicationId);
  const { data: app, error, reload } = useODResource(endpoint);
  const [action, setAction] = useState('');
  const [remarks, setRemarks] = useState('');
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState('');
  const dialog = useRef(null);
  const { state } = useLocation();
  const base = admin ? '/admin/applications' : hod ? '/hod/applications' : tutor ? '/tutor/applications' : '/student/applications';
  const back = priorMonitor ? '/hod/prior-od'
    : hod && (state?.history || (app && app.status !== 'UNDER_HOD_REVIEW')) ? '/hod/history' : base;
  const rejectedEvidence = app?.status === 'REJECTED' && app.history.some(({ from_status, to_status }) =>
    evidenceOpen.has(from_status) || evidenceOpen.has(to_status) || from_status === 'UNDER_HOD_REVIEW');
  const hasEvidenceStage = app && (evidenceOpen.has(app.status) ||
    ['UNDER_HOD_REVIEW', 'HOD_CORRECTION_REQUESTED', 'OD_FINALIZED'].includes(app.status) || rejectedEvidence);
  const tutorDecisions = app?.status === 'UNDER_TUTOR_CORRECTION_REVIEW'
    ? [{ value: 'PREAPPROVE', label: 'Forward correction to HOD' }, ...decisions.slice(1)]
    : decisions;

  async function openDocument(document, preview = false) {
    setActionError('');
    const endpoint = API_ENDPOINTS.APPLICATIONS.DOCUMENT(applicationId, document.id);
    try {
      if (preview) await viewODFile(endpoint);
      else await downloadODFile(endpoint, document.filename);
    } catch (failure) {
      setActionError(odError(failure, preview ? 'The document preview could not be opened.' : 'The document could not be downloaded.'));
    }
  }

  async function decide(event) {
    event.preventDefault();
    setSaving(true);
    setActionError('');
    try {
      await apiClient((hod ? API_ENDPOINTS.HOD : API_ENDPOINTS.TUTOR).DECISION(applicationId), {
        method: 'POST', body: JSON.stringify({ action, remarks, expected_revision: app.revision }),
      });
      dialog.current?.close();
      setAction('');
      setRemarks('');
      reload();
    } catch (failure) {
      setActionError(odError(failure, 'The decision could not be saved.'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-4xl space-y-5">
      <div className="flex justify-between gap-3">
        <Link className="text-sm text-brand-primary underline" to={back}>{back === '/hod/history' ? 'Back to decision history' : 'Back to applications'}</Link>
        <Button variant="secondary" size="sm" onClick={() => { setActionError(''); reload(); }}>Refresh</Button>
      </div>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {actionError && <p role="alert" className="text-sm text-rose-700">{actionError}</p>}
      {!app && !error && <p role="status" className="text-sm">Loading application…</p>}
      {state?.submissionNotice && <p role="status" className="text-sm text-brand-primary">{state.submissionNotice}</p>}
      {app && (
        <>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-xl font-bold text-brand-dark">{app.event_name}</h1>
              <p className="mt-1 text-xs text-brand-muted">{app.application_number}</p>
            </div>
            <Badge variant={statusVariant(app.status)}>{statusLabel(app.status)}</Badge>
          </div>
          <Card title="Event information">
            <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs text-brand-muted">Student</dt><dd>{app.student_name} ({app.student_roll_number})</dd></div>
              <div><dt className="text-xs text-brand-muted">Assigned tutor</dt><dd>{app.tutor_name}</dd></div>
              {admin && <>
                <div><dt className="text-xs text-brand-muted">Department</dt><dd>{app.department_name || 'Unavailable'}</dd></div>
                <div><dt className="text-xs text-brand-muted">Current department HOD</dt><dd>{app.current_hod_name || 'Unassigned'}</dd></div>
              </>}
              <div><dt className="text-xs text-brand-muted">Organized by</dt><dd>{app.host_institution}</dd></div>
              <div><dt className="text-xs text-brand-muted">Venue</dt><dd>{app.venue_location}</dd></div>
              <div><dt className="text-xs text-brand-muted">Event category</dt>
                <dd className="capitalize">{app.event_category.replaceAll('_', ' ').toLowerCase()}</dd>
              </div>
              <div className="sm:col-span-2"><dt className="text-xs text-brand-muted">Event dates</dt>
                <dd>{app.event_days.map((day) => `${day.event_date} (${day.session.replaceAll('_', ' ').toLowerCase()})`).join(', ')}</dd>
              </div>
              <div className="sm:col-span-2"><dt className="text-xs text-brand-muted">Purpose</dt>
                <dd className="whitespace-pre-wrap break-words">{app.description}</dd>
              </div>
            </dl>
          </Card>
          {app.expected_venue && (hasEvidenceStage && (tutor || hod) ? (
            <MapODPanel key={app.id} applicationId={app.id} readOnly />
          ) : (
            <Card title="Expected venue pin" bodyClassName="space-y-2">
              <VenueMap venue={app.expected_venue} basemap />
              <p className="text-sm">{app.expected_venue.latitude.toFixed(6)}, {app.expected_venue.longitude.toFixed(6)}</p>
              {tutor && ['SUBMITTED', 'UNDER_TUTOR_REVIEW'].includes(app.status) && (
                <p className="text-sm text-brand-muted">Review the venue pin before approval. Request a correction if it is incorrect.</p>
              )}
            </Card>
          ))}
          {!admin && !tutor && !hod && app.expected_venue && app.post_od_eligible && (
            <Link className="text-sm font-medium text-brand-primary underline" to={'/student/post-od/' + app.id + '/map'}>Open Map OD</Link>
          )}
          {!admin && !priorMonitor && <Card title="Documents">
            {app.documents.length ? (
              <ul className="space-y-3">
                {app.documents.map((doc) => (
                  <li key={doc.id} className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0 break-words text-sm">
                      <div>{documentLabels[doc.document_type] ?? 'Supporting document'}</div>
                      <div className="text-xs text-brand-muted">{doc.filename}</div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {hod && <Button size="sm" variant="secondary" onClick={() => openDocument(doc, true)}>View</Button>}
                      <Button size="sm" variant="secondary" icon={Download} onClick={() => openDocument(doc)}>Download</Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-brand-muted">No documents available.</p>}
          </Card>}
          <Card title="Status history">
            {app.history.length ? (
              <ol className="space-y-3">
                {app.history.map((entry) => (
                  <li key={entry.id} className="border-l-2 border-brand-border pl-3">
                    <p className="text-sm font-medium">
                      {entry.hod_name ? ({
                        OD_FINALIZED: 'HOD approved and finalized OD',
                        REJECTED: 'HOD rejected the application',
                        HOD_CORRECTION_REQUESTED: 'HOD requested correction',
                      }[entry.to_status]) : statusLabel(entry.to_status)}
                    </p>
                    {entry.hod_name && <p className="text-xs text-brand-muted">{entry.hod_name}</p>}
                    <p className="text-xs text-brand-muted">{new Date(entry.created_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(entry.created_at)
                      ? entry.created_at : `${entry.created_at}Z`).toLocaleString()}</p>
                    {entry.remarks && <p className="mt-1 whitespace-pre-wrap break-words text-sm">{entry.remarks}</p>}
                  </li>
                ))}
              </ol>
            ) : <p className="text-sm text-brand-muted">No status changes recorded.</p>}
          </Card>
          {app.status === 'UNDER_HOD_REVIEW' && !hod && (
            <p className="text-sm text-brand-muted">The tutor verified all event days. The application is awaiting the department HOD’s decision.</p>
          )}
          {!admin && !hod && app.post_od_eligible && !app.documents.some((document) => document.document_type === 'ORIGINAL_SIGNED_OD_FORM') && (
            <p className="text-sm text-brand-muted">The signed OD form is required before HOD review. Upload will be available with the full Post OD submission.</p>
          )}
          {!admin && !priorMonitor && hasEvidenceStage && (
            <EvidencePanel key={app.id} applicationId={app.id} tutor={tutor} readOnly={hod} onChange={reload} />
          )}
          {!admin && !tutor && !hod && correctionRequested.has(app.status) && (
            <Link className="inline-block rounded-md bg-brand-primary px-4 py-2 text-sm text-white"
              to={`${base}/${app.id}/correct`}>Correct and resubmit</Link>
          )}
          {hod && !priorMonitor && app.status === 'UNDER_HOD_REVIEW' && (
            <Card title="HOD decision">
              <Button onClick={() => { setActionError(''); dialog.current.showModal(); }}>Record decision</Button>
              <dialog ref={dialog} aria-labelledby="hod-decision-title"
                className="w-[calc(100%-2rem)] max-w-lg rounded-lg border border-brand-border p-6 backdrop:bg-slate-900/50"
                onCancel={(event) => { if (saving) event.preventDefault(); }}>
                <form className="space-y-4" onSubmit={decide}>
                  <h2 id="hod-decision-title" className="font-semibold text-brand-dark">Record HOD decision</h2>
                  <Select label="Decision" required options={hodDecisions} value={action}
                    onChange={(event) => setAction(event.target.value)} />
                  <div className="space-y-1">
                    <label className="block text-xs font-medium" htmlFor="hod-remarks">
                      {action === 'APPROVE' ? 'Remarks (optional)' : 'Remarks (required for rejection or correction)'}
                    </label>
                    <textarea id="hod-remarks" rows={4} maxLength={2000} required={action !== 'APPROVE'}
                      value={remarks} className="block w-full rounded-md border border-slate-300 p-2 text-sm"
                      onChange={(event) => setRemarks(event.target.value)} />
                  </div>
                  {actionError && <p role="alert" className="text-sm text-rose-700">{actionError}</p>}
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button variant="secondary" disabled={saving} onClick={() => dialog.current.close()}>Cancel</Button>
                    <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save decision'}</Button>
                  </div>
                </form>
              </dialog>
            </Card>
          )}
          {tutor && reviewable.has(app.status) && (
            <Card title="Tutor decision">
              <form className="space-y-3" onSubmit={decide}>
                <Select label="Decision" required options={tutorDecisions} value={action}
                  onChange={(event) => setAction(event.target.value)} />
                <label className="block text-xs font-medium" htmlFor="review-remarks">Remarks</label>
                <textarea id="review-remarks" rows={3} maxLength={2000} required value={remarks}
                  className="block w-full rounded-md border border-slate-300 p-2 text-sm"
                  onChange={(event) => setRemarks(event.target.value)} />
                <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save decision'}</Button>
              </form>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
