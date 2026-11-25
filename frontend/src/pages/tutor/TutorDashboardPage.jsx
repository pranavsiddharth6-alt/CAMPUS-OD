import React, { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Select } from '../../components/ui/Select';
import { API_ENDPOINTS } from '../../services/api';
import { useODResource } from '../../services/od';

const categories = [
  ['total_students', 'Total Students'],
  ['hostel_students', 'Hostel Students'],
  ['outside_staying', 'Outside Staying'],
  ['guardian', 'Guardian'],
];

export function TutorDashboardPage() {
  const [classId, setClassId] = useState('');
  const initial = useODResource(API_ENDPOINTS.TUTOR.DASHBOARD());
  const selection = useODResource(classId ? API_ENDPOINTS.TUTOR.DASHBOARD(classId) : null);
  const { data, error } = classId ? selection : initial;
  const classes = data?.classes ?? initial.data?.classes ?? [];
  const selectedId = classId || data?.selected_class_id;
  const currentClass = classes.find(({ id }) => id === selectedId);
  const statistics = data?.statistics;
  const total = statistics?.total_students;

  function refresh() {
    initial.reload();
    if (classId) selection.reload();
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold text-brand-dark">Faculty Dashboard</h1>
          {currentClass && <p className="mt-1 text-sm text-brand-muted">{currentClass.department} · {currentClass.academic_year}</p>}
        </div>
        <Button variant="secondary" size="sm" icon={RefreshCw} onClick={refresh}>Refresh</Button>
      </div>

      {classes.length > 1 ? (
        <Select className="max-w-sm" label="Class" value={selectedId ?? ''} onChange={(event) => setClassId(event.target.value)}
          options={classes.map(({ id, name }) => ({ value: id, label: name }))} />
      ) : currentClass && <p className="text-sm font-medium text-brand-dark">{currentClass.name}</p>}

      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {error && classId && <Button variant="secondary" size="sm" onClick={() => {
        setClassId('');
        initial.reload();
      }}>Return to assigned classes</Button>}
      {!data && !error && <p role="status" className="text-sm">Loading class statistics…</p>}
      {data && !classes.length && <Card><p className="text-sm">You have no active classes assigned in the current academic year.</p></Card>}
      {statistics && (
        <>
          {total.total === 0 && <p className="text-sm text-brand-muted">There are no eligible students enrolled in this class.</p>}
          <section aria-label="Class statistics" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {categories.map(([key, name]) => {
              const counts = statistics[key];
              return (
                <Card key={key} className="border-t-2 border-t-brand-primary">
                  <h2 className="text-sm font-semibold text-brand-dark">{name}</h2>
                  <p className="mt-2 text-3xl font-bold tabular-nums text-brand-primary" aria-label={`Total ${counts.total}`}>{counts.total}</p>
                  <dl className="mt-4 flex flex-wrap gap-x-5 gap-y-2 border-t border-brand-border pt-3 text-sm">
                    <div className="flex gap-2"><dt>Boys</dt><dd className="font-semibold tabular-nums">{counts.boys}</dd></div>
                    <div className="flex gap-2"><dt>Girls</dt><dd className="font-semibold tabular-nums">{counts.girls}</dd></div>
                  </dl>
                </Card>
              );
            })}
          </section>
          {total.total > total.boys + total.girls && (
            <p className="text-sm text-brand-muted">Totals include students without a recorded gender. Boys and girls counts use recorded values.</p>
          )}
        </>
      )}
    </div>
  );
}
