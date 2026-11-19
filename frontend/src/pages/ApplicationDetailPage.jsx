import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Download } from 'lucide-react';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { EvidencePanel } from '../components/od/EvidencePanel';
import { API_ENDPOINTS, apiClient } from '../services/api';
import { downloadODFile, evidenceOpen, odError, reviewable, statusLabel, statusVariant, useODResource } from '../services/od';

const documentLabels = {
  ORIGINAL_SIGNED_OD_FORM: 'Original signed OD form',
  EVENT_INVITATION: 'Event invitation',
  PARENT_CONSENT: 'Parent consent',
};
const decisions = [
  { value: 'PREAPPROVE', label: 'Preapprove' },
  { value: 'REJECT', label: 'Reject' },
  { value: 'REQUEST_CORRECTION', label: 'Request correction' },
];

export function ApplicationDetailPage({ tutor = false }) {
  const { applicationId } = useParams();
  const { data: app, error, reload } = useODResource(API_ENDPOINTS.APPLICATIONS.DETAIL(applicationId));
  const [action, setAction] = useState('');
  const [remarks, setRemarks] = useState('');
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState('');
  const base = tutor ? '/tutor/applications' : '/student/applications';

  async function download(document) {
    setActionError('');
    try {
      await downloadODFile(API_ENDPOINTS.APPLICATIONS.DOCUMENT(applicationId, document.id), document.filename);
    } catch (failure) {
      setActionError(odError(failure, 'The document could not be downloaded.'));
    }
  }

  async function decide(event) {
    event.preventDefault();
    setSaving(true);
    setActionError('');
    try {
      await apiClient(API_ENDPOINTS.TUTOR.DECISION(applicationId), {
        method: 'POST', body: JSON.stringify({ action, remarks, expected_revision: app.revision }),
      });
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
        <Link className="text-sm text-brand-primary underline" to={base}>Back to applications</Link>
        <Button variant="secondary" size="sm" onClick={() => { setActionError(''); reload(); }}>Refresh</Button>
      </div>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {actionError && <p role="alert" className="text-sm text-rose-700">{actionError}</p>}
      {!app && !error && <p role="status" className="text-sm">Loading application…</p>}
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
              <div><dt className="text-xs text-brand-muted">Host</dt><dd>{app.host_institution}</dd></div>
              <div><dt className="text-xs text-brand-muted">Venue</dt><dd>{app.venue_location}</dd></div>
              <div className="sm:col-span-2"><dt className="text-xs text-brand-muted">Event dates</dt>
                <dd>{app.event_days.map((day) => `${day.event_date} (${day.session.replaceAll('_', ' ').toLowerCase()})`).join(', ')}</dd>
              </div>
              <div className="sm:col-span-2"><dt className="text-xs text-brand-muted">Purpose</dt>
                <dd className="whitespace-pre-wrap break-words">{app.description}</dd>
              </div>
            </dl>
          </Card>
          <Card title="Documents">
            {app.documents.length ? (
              <ul className="space-y-3">
                {app.documents.map((doc) => (
                  <li key={doc.id} className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0 break-words text-sm">
                      <div>{documentLabels[doc.document_type] ?? 'Supporting document'}</div>
                      <div className="text-xs text-brand-muted">{doc.filename}</div>
                    </div>
                    <Button size="sm" variant="secondary" icon={Download} onClick={() => download(doc)}>Download</Button>
                  </li>
                ))}
              </ul>
            ) : <p className="text-sm text-brand-muted">No documents available.</p>}
          </Card>
          <Card title="Status history">
            {app.history.length ? (
              <ol className="space-y-3">
                {app.history.map((entry) => (
                  <li key={entry.created_at} className="border-l-2 border-brand-border pl-3">
                    <p className="text-sm font-medium">{statusLabel(entry.to_status)}</p>
                    <p className="text-xs text-brand-muted">{new Date(entry.created_at.endsWith('Z') || /[+-]\d\d:\d\d$/.test(entry.created_at)
                      ? entry.created_at : `${entry.created_at}Z`).toLocaleString()}</p>
                    {entry.remarks && <p className="mt-1 whitespace-pre-wrap break-words text-sm">{entry.remarks}</p>}
                  </li>
                ))}
              </ol>
            ) : <p className="text-sm text-brand-muted">No status changes recorded.</p>}
          </Card>
          {(evidenceOpen.has(app.status) || ['OD_FINALIZED', 'REJECTED'].includes(app.status)) && (
            <EvidencePanel key={app.id} applicationId={app.id} tutor={tutor} onChange={reload} />
          )}
          {!tutor && app.status === 'CORRECTION_REQUESTED' && (
            <Link className="inline-block rounded-md bg-brand-primary px-4 py-2 text-sm text-white"
              to={`${base}/${app.id}/correct`}>Correct and resubmit</Link>
          )}
          {tutor && reviewable.has(app.status) && (
            <Card title="Tutor decision">
              <form className="space-y-3" onSubmit={decide}>
                <Select label="Decision" required options={decisions} value={action}
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
