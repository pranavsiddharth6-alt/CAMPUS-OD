import React from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { API_ENDPOINTS } from '../../services/api';
import { dateRange, statusLabel, statusVariant, useODResource } from '../../services/od';

export function PostODPage() {
  const { data, error, reload } = useODResource(API_ENDPOINTS.APPLICATIONS.LIST);
  const eligible = data?.filter((app) => app.post_od_eligible);
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-brand-dark">Post OD</h1>
        <Button variant="secondary" onClick={reload}>Refresh</Button>
      </div>
      <p className="text-sm text-brand-muted">Approved Prior OD applications appear here when participation evidence or corrections are open.</p>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {!data && !error && <p role="status" className="text-sm">Loading applications…</p>}
      {eligible?.length === 0 && <Card><p className="text-sm">No approved applications are open for Post OD.</p></Card>}
      <ul className="grid gap-3 lg:grid-cols-2">
        {eligible?.map((app) => (
          <li key={app.id}>
            <Card>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <Link className="font-medium text-brand-primary underline" to={'/student/applications/' + app.id}>{app.event_name}</Link>
                  <p className="text-sm text-brand-muted">{dateRange(app)}</p>
                </div>
                <div className="flex flex-col items-end gap-2">
                  <Badge variant={statusVariant(app.status)}>{statusLabel(app.status)}</Badge>
                  <Link className="text-sm font-medium text-brand-primary underline" to={'/student/post-od/' + app.id + '/map'}>
                    Open Map OD
                  </Link>
                </div>
              </div>
            </Card>
          </li>
        ))}
      </ul>
      <Link className="text-sm text-brand-primary underline" to="/student/applications">View application history</Link>
    </div>
  );
}
