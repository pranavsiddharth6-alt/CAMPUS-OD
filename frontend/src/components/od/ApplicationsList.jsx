import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { PlusCircle, RefreshCw } from 'lucide-react';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { Card } from '../ui/Card';
import { Input } from '../ui/Input';
import { Select } from '../ui/Select';
import { Table, TableCell, TableRow } from '../ui/Table';
import { API_ENDPOINTS } from '../../services/api';
import { dateRange, reviewable, statusLabel, statusVariant, useODResource } from '../../services/od';

export function ApplicationsList({ tutor = false, dashboard = false }) {
  const portal = tutor ? 'tutor' : 'student';
  const { data, error, reload } = useODResource(tutor ? API_ENDPOINTS.TUTOR.APPLICATIONS : API_ENDPOINTS.APPLICATIONS.LIST);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const title = dashboard ? (tutor ? 'Tutor Dashboard' : 'Student Dashboard')
    : tutor ? 'Assigned OD Applications' : 'My On-Duty Applications';
  const records = data ?? [];
  const options = [...new Set(records.map(({ status }) => status))]
    .map((status) => ({ value: status, label: statusLabel(status) }));
  const query = search.trim().toLowerCase();
  const matching = records.filter((application) =>
    (!filter || application.status === filter) &&
    [application.event_name, application.application_number, application.student_name, application.student_roll_number]
      .some((value) => value.toLowerCase().includes(query)));

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-brand-dark">{title}</h1>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" icon={RefreshCw} onClick={reload}>Refresh</Button>
          {!tutor && (
            <Link className="inline-flex items-center gap-2 rounded-md bg-brand-primary px-4 py-2 text-sm font-medium text-white"
              to="/student/applications/new"><PlusCircle className="h-4 w-4" /> Apply for OD</Link>
          )}
        </div>
      </div>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {!data && !error && <p role="status" className="text-sm">Loading applications…</p>}
      {data && dashboard && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            ['Applications', records.length],
            ['Awaiting review', records.filter((app) => reviewable.has(app.status)).length],
            ['Corrections requested', records.filter((app) => app.status === 'CORRECTION_REQUESTED').length],
            ['Preapproved', records.filter((app) => app.status === 'PRE_APPROVED').length],
          ].map(([label, count]) => (
            <Card key={label}>
              <p className="text-xs text-brand-muted">{label}</p><p className="text-xl font-semibold">{count}</p>
            </Card>
          ))}
        </div>
      )}
      {data && (records.length === 0 ? (
        <Card><p className="text-sm text-brand-muted">{tutor ? 'No applications are assigned to you.' : 'You have no applications yet.'}</p></Card>
      ) : (
        <>
          <Card bodyClassName="grid gap-3 sm:grid-cols-2">
            <Input label="Search applications" value={search} onChange={(event) => setSearch(event.target.value)} />
            <Select label="Status" placeholder={null} value={filter} onChange={(event) => setFilter(event.target.value)}
              options={[{ value: '', label: 'All statuses' }, ...options]} />
          </Card>
          <Table headers={['Application', 'Event', 'Dates', tutor ? 'Student' : 'Assigned tutor', 'Status', '']}>
            {matching.map((app) => (
              <TableRow key={app.id}>
                <TableCell className="font-medium text-brand-primary">{app.application_number}</TableCell>
                <TableCell>{app.event_name}<div className="text-xs text-brand-muted">{app.venue_location}</div></TableCell>
                <TableCell>{dateRange(app)}<div className="text-xs text-brand-muted">{app.total_days} day(s)</div></TableCell>
                <TableCell>{tutor ? `${app.student_name} (${app.student_roll_number})` : app.tutor_name}</TableCell>
                <TableCell><Badge variant={statusVariant(app.status)}>{statusLabel(app.status)}</Badge></TableCell>
                <TableCell>
                  <Link className="font-medium text-brand-primary underline" to={`/${portal}/applications/${app.id}`}>
                    {tutor && reviewable.has(app.status) ? 'Review' : 'View'}
                  </Link>
                </TableCell>
              </TableRow>
            ))}
          </Table>
          {!matching.length && <p className="text-sm text-brand-muted">No applications match these filters.</p>}
        </>
      ))}
    </div>
  );
}
