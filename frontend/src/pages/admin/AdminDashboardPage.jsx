import React from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../../components/ui/Card';
import { API_ENDPOINTS } from '../../services/api';
import { statusLabel, useODResource } from '../../services/od';

export function AdminDashboardPage() {
  const { data, error } = useODResource(API_ENDPOINTS.ADMIN.METRICS);
  return <div className="space-y-5">
    <h1 className="text-xl font-bold text-brand-dark">Admin Overview</h1>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">Loading administrative statistics…</p>}
    {data && <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[['STUDENT', 'Total students'], ['TUTOR', 'Total faculty'], ['HOD', 'Total HODs']].map(([role, label]) => {
          const counts = data.accounts[role];
          return <Card key={role} title={label}>
            <p className="text-2xl font-semibold">{counts.ACTIVE + counts.PENDING_ACTIVATION + counts.DISABLED}</p>
            <p className="text-sm">{counts.ACTIVE} active · {counts.PENDING_ACTIVATION} invited · {counts.DISABLED} disabled</p>
          </Card>;
        })}
        <Card title="Total departments">
          <p className="text-2xl font-semibold">{data.departments.active + data.departments.inactive}</p>
          <p className="text-sm">{data.departments.active} active · {data.departments.inactive} inactive</p>
        </Card>
      </div>
      <Card title={'OD applications · ' + Object.values(data.applications).reduce((total, count) => total + count, 0)}
        action={<Link className="text-sm underline" to="/admin/applications">View applications</Link>}>
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.entries(data.applications).map(([status, count]) => <div key={status} className="flex justify-between gap-2 border-b pb-1">
            <dt className="text-sm">{statusLabel(status)}</dt><dd className="font-semibold">{count}</dd>
          </div>)}
        </dl>
      </Card>
    </>}
  </div>;
}
