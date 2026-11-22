import React from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { API_ENDPOINTS } from '../../services/api';
import { dateRange, statusLabel, statusVariant, useODResource } from '../../services/od';

const linkStyle = 'font-medium text-brand-primary underline';

export function HODDashboardPage() {
  const { data, error, reload } = useODResource(API_ENDPOINTS.HOD.DASHBOARD);
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-brand-dark">HOD Dashboard</h1>
        <Button variant="secondary" onClick={reload}>Refresh</Button>
      </div>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {!data && !error && <p role="status" className="text-sm">Loading department summary…</p>}
      {data && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[
            ['Pending review', data.pending], ['Finalized', data.approved], ['Rejected', data.rejected],
            ['Completed', data.approved + data.rejected],
          ].map(([label, count]) => (
            <Card key={label}>
              <p className="text-sm text-brand-muted">{label}</p>
              <p className="text-xl font-semibold">{count}</p>
            </Card>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-4 text-sm">
        <Link className={linkStyle} to="/hod/applications">Review pending requests</Link>
        <Link className={linkStyle} to="/hod/history">View decision history</Link>
      </div>
    </div>
  );
}

export function HODApplicationsPage({ history = false }) {
  const view = history ? 'history' : 'pending';
  const { data: records, error, reload } = useODResource(API_ENDPOINTS.HOD.APPLICATIONS + '?view=' + view);
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-brand-dark">{history ? 'Decision History' : 'Pending OD Requests'}</h1>
        <Button variant="secondary" onClick={reload}>Refresh</Button>
      </div>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {!records && !error && <p role="status" className="text-sm">Loading applications…</p>}
      {records?.length === 0 && (
        <Card><p className="text-sm text-brand-muted">{history ? 'No decisions recorded yet.' : 'No applications are awaiting HOD review.'}</p></Card>
      )}
      <ul className="grid gap-3 xl:grid-cols-2">
        {records?.map((app) => (
          <li key={app.id}>
            <Card>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 break-words text-sm">
                  <Link className={linkStyle} state={{ history }} to={'/hod/applications/' + app.id}>{app.event_name}</Link>
                  <p>{app.student_name} ({app.student_roll_number})</p>
                  <p className="text-xs text-brand-muted">{dateRange(app)} · {app.venue_location}</p>
                </div>
                <Badge variant={statusVariant(app.status)}>{statusLabel(app.status)}</Badge>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
