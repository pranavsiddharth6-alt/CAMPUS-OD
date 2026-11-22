import React, { useEffect, useState } from 'react';
import { UserPlus } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { API_ENDPOINTS, apiClient } from '../../services/api';
import { odError } from '../../services/od';

export function AdminUsersPage() {
  const [roster, setRoster] = useState(null);
  const [created, setCreated] = useState({});
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    apiClient(API_ENDPOINTS.ADMIN.DEMO_ROSTER)
      .then((data) => { if (active) setRoster(data); })
      .catch(() => { if (active) setError('The approved demo roster could not be loaded.'); });
    return () => { active = false; };
  }, []);

  async function provision(endpoint, record) {
    setError('');
    setBusy(record.email);
    try {
      const result = await apiClient(endpoint, { method: 'POST', body: JSON.stringify(record) });
      setCreated((previous) => ({ ...previous, [record.email]: result }));
    } catch (failure) {
      setError(odError(failure, 'The demo account could not be created.'));
    } finally {
      setBusy('');
    }
  }

  const groups = roster ? [
    { title: 'Students', records: roster.students, endpoint: API_ENDPOINTS.ADMIN.STUDENTS },
    { title: 'Tutors', records: roster.tutors, endpoint: API_ENDPOINTS.ADMIN.TUTORS },
    { title: 'Heads of Department', records: roster.hods, endpoint: API_ENDPOINTS.ADMIN.HODS },
  ] : [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-bold text-brand-dark">Provision Demo Accounts</h1>
        <p className="mt-1 text-xs text-brand-muted">Create invited accounts from the approved fictional roster.</p>
      </div>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {!roster && !error && <p role="status" className="text-sm">Loading the demo roster…</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        {groups.map(({ title, records, endpoint }) => (
          <Card key={title} title={title}>
            {records.map((record) => {
              const result = created[record.email];
              return (
                <div key={record.email} className="space-y-3">
                  <div>
                    <p className="text-sm font-semibold text-brand-dark">{record.full_name}</p>
                    <p className="text-xs text-brand-muted">{record.email}</p>
                    {endpoint === API_ENDPOINTS.ADMIN.HODS && (
                      <p className="text-xs text-brand-muted">Initial assignment · Demo Department</p>
                    )}
                  </div>
                  <Button icon={UserPlus} disabled={Boolean(busy || result)} onClick={() => provision(endpoint, record)}>
                    {busy === record.email ? 'Creating…' : 'Create account'}
                  </Button>
                  {result && (
                    <p role="status" className="break-words text-xs text-slate-700">
                      {result.invitation_delivered
                        ? 'Account created. Give the local operator this invitation ID to retrieve the code.'
                        : 'Account created. The invitation could not be saved to the local outbox.'}
                      <br />{result.invitation_id}
                    </p>
                  )}
                </div>
              );
            })}
          </Card>
        ))}
      </div>
    </div>
  );
}
