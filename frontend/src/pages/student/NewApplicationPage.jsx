import React, { useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { Select } from '../../components/ui/Select';
import { API_ENDPOINTS, apiClient } from '../../services/api';
import { correctionRequested, odError, useODResource } from '../../services/od';
import { VenuePinField } from '../../components/od/VenueMap';

const categories = [
  ['TECHNICAL', 'Technical'], ['SPORTS', 'Sports'], ['CULTURAL', 'Cultural'], ['ACADEMIC', 'Academic'],
  ['PAPER_PRESENTATION', 'Paper presentation'], ['NSS_NCC', 'NSS / NCC'], ['OTHER', 'Other'],
].map(([value, label]) => ({ value, label }));
const sessions = [
  { value: 'FULL_DAY', label: 'Full day' }, { value: 'FORENOON', label: 'Forenoon' },
  { value: 'AFTERNOON', label: 'Afternoon' },
];
const fields = [
  ['event_name', 'Event name', 200], ['host_institution', 'Organized by', 200], ['venue_location', 'Event venue', 255],
];
const uploadFields = [
  ['event_invitation', 'Event invitation'], ['parent_consent', 'Parent consent'],
];
const blankDay = () => ({ event_date: '', session: 'FULL_DAY' });
const indexPath = '/student/applications';

function ApplicationForm({ application }) {
  const editing = Boolean(application);
  const fixedEvent = application?.status === 'HOD_CORRECTION_REQUESTED';
  const navigate = useNavigate();
  const [days, setDays] = useState(() => (application?.event_days ?? [blankDay()]).map((day, key) => ({ ...day, key })));
  const nextDayKey = useRef(days.length);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [venue, setVenue] = useState(application?.expected_venue ?? null);

  async function submit(event) {
    event.preventDefault();
    if (!editing && !venue) {
      setError('Select the expected event venue before submitting.');
      return;
    }
    const form = new FormData(event.currentTarget);
    const dates = form.getAll('event-date');
    const sessionsByDay = form.getAll('event-session');
    const eventDays = days.map(({ event_date, session }, index) => ({
      event_date: fixedEvent ? event_date : dates[index],
      session: fixedEvent ? session : sessionsByDay[index],
    }));
    if (new Set(eventDays.map(({ event_date }) => event_date)).size !== eventDays.length) {
      setError('Use a different date for each event day.');
      return;
    }
    const details = Object.fromEntries(
      [...fields.map(([name]) => name), 'event_category', 'description'].map((name) => [name, form.get(name)]),
    );
    if (fixedEvent) {
      for (const name of [...fields.map(([name]) => name), 'event_category']) details[name] = application[name];
    }
    details.event_days = eventDays;
    if (venue && !fixedEvent) details.expected_venue = venue;
    if (editing) details.expected_revision = application.revision;

    const body = new FormData();
    body.append('details', JSON.stringify(details));
    for (const [name] of uploadFields) {
      const file = form.get(name);
      if (file?.name) body.append(name, file);
    }
    setError('');
    setBusy(true);
    try {
      const result = await apiClient(editing ? API_ENDPOINTS.APPLICATIONS.RESUBMIT(application.id) : API_ENDPOINTS.APPLICATIONS.CREATE,
        { method: 'POST', body });
      navigate(indexPath + '/' + result.id, {
        replace: true, state: { submissionNotice: editing ? 'Application resubmitted.' : 'Prior OD submitted for tutor review.' },
      });
    } catch (failure) {
      setError(odError(failure, 'The application could not be saved.'));
    } finally {
      setBusy(false);
    }
  }

  const back = editing ? indexPath + '/' + application.id : indexPath;
  return (
    <div className="max-w-3xl space-y-5">
      <Link to={back} className="text-sm text-brand-primary underline">Back to applications</Link>
      <h1 className="text-xl font-bold text-brand-dark">
        {editing ? 'Correct OD application' : 'Prior OD'}
      </h1>
      {editing ? (
        <Card title="Review feedback">
          <p className="whitespace-pre-wrap break-words text-sm">{application.history.at(-1)?.remarks}</p>
        </Card>
      ) : <p className="text-sm text-brand-muted">Your application goes to the active tutor for your class and academic year.</p>}
      <form className="space-y-5" onSubmit={submit}>
        <Card title="Event information" bodyClassName="space-y-3">
          {fields.map(([name, label, maxLength]) => (
            <Input key={name} label={label} name={name} disabled={fixedEvent} required maxLength={maxLength} defaultValue={application?.[name]} />
          ))}
          <Select label="Event category" name="event_category" disabled={fixedEvent} required options={categories}
            defaultValue={application?.event_category ?? ''} />
          <label className="block text-xs font-medium" htmlFor="event-description">Purpose and description</label>
          <textarea id="event-description" name="description" rows={4} maxLength={3000} required
            defaultValue={application?.description} className="block w-full rounded-md border border-slate-300 p-2 text-sm" />
        </Card>
        <Card title="Expected event venue">
          <VenuePinField value={venue} onChange={setVenue} locked={fixedEvent} />
        </Card>
        <Card title="Event dates" bodyClassName="space-y-3">
          {days.map((day, index) => (
            <div key={day.key} className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_auto]">
              <div className="min-w-0">
                <Input label={'Date ' + (index + 1)} name="event-date" type="date" disabled={fixedEvent}
                  required defaultValue={day.event_date} />
              </div>
              <div className="min-w-0">
                <Select label={'Session ' + (index + 1)} name="event-session" options={sessions}
                  disabled={fixedEvent} defaultValue={day.session} />
              </div>
              <Button variant="ghost" disabled={fixedEvent || days.length === 1} aria-label={'Remove date ' + (index + 1)}
                onClick={() => setDays((previous) => previous.filter((_, position) => position !== index))}>Remove</Button>
            </div>
          ))}
          {fixedEvent ? (
            <p className="text-xs text-brand-muted">The verified event and schedule are fixed. Update the description or add supporting documents below. Your tutor can reopen evidence for individual days.</p>
          ) : (
            <Button variant="secondary" onClick={() => {
              const day = { ...blankDay(), key: nextDayKey.current++ };
              setDays((previous) => [...previous, day]);
            }}>Add date</Button>
          )}
        </Card>
        <Card title="Supporting documents" bodyClassName="space-y-3">
          <p className="text-xs text-brand-muted">
            {editing ? 'Add supporting documents if needed. Existing documents stay on the application.' : 'Optional. The signed OD form is required for Post OD.'}
          </p>
          {uploadFields.map(([name, label]) => (
            <Input key={name} label={label} type="file" name={name}
              accept=".pdf,.png,.jpg,.jpeg" />
          ))}
        </Card>
        {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
        <div className="flex justify-end">
          <Button type="submit" disabled={busy}>{busy ? 'Saving…' : editing ? 'Resubmit for review' : 'Submit Prior OD'}</Button>
        </div>
      </form>
    </div>
  );
}

export function NewApplicationPage() {
  const { applicationId } = useParams();
  const { data, error, reload } = useODResource(applicationId ? API_ENDPOINTS.APPLICATIONS.DETAIL(applicationId) : null);
  if (!applicationId) return <ApplicationForm key="new" />;
  if (error) return <div role="alert" className="space-y-2"><p>{error}</p><Button onClick={reload}>Try again</Button></div>;
  if (!data) return <p role="status">Loading application…</p>;
  if (!correctionRequested.has(data.status)) {
    return <Link to={indexPath + '/' + applicationId} className="text-brand-primary underline">View application</Link>;
  }
  return <ApplicationForm key={data.revision ?? data.id} application={data} />;
}
