import React, { useEffect, useState } from 'react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Select } from '../../components/ui/Select';
import { API_ENDPOINTS, apiClient } from '../../services/api';
import { odError, useODResource } from '../../services/od';

function ClassMapping({ item, onSave }) {
  const assigned = item.assignment?.active ? item.assignment.tutor_id : '';
  const [selection, setSelection] = useState(assigned);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  useEffect(() => setSelection(assigned), [assigned]);
  async function save(event) {
    event.preventDefault();
    setBusy(true);
    setNotice('');
    try {
      await apiClient(API_ENDPOINTS.ADMIN.ASSIGN_TUTOR(item.id), {
        method: 'PUT', body: JSON.stringify({ tutor_id: selection || null }),
      });
      setNotice('Class mapping saved.');
      onSave();
    } catch (failure) {
      setNotice(odError(failure, 'The class mapping could not be saved.'));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card title={item.name} subtitle={`${item.department} · ${item.academic_year}${item.current_year ? ' (current)' : ''}`}
      bodyClassName="space-y-3">
      <p className="text-sm">Assigned tutor: {item.assignment?.active ? item.assignment.tutor_name : 'Unassigned'}</p>
      <p className="text-sm">Active enrollments: {item.students.length
        ? item.students.map((student) => `${student.name} (${student.roll_number})`).join(', ') : 'None'}</p>
      <form className="space-y-2" onSubmit={save}>
        <Select id={`class-tutor-${item.id}`} label="Class tutor" value={selection} placeholder={null}
          onChange={(event) => setSelection(event.target.value)}
          options={[{ value: '', label: 'No active tutor' }, ...item.available_tutors.map(({ id, name }) => ({ value: id, label: name }))]} />
        <Button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save tutor mapping'}</Button>
        {notice && <p className="text-xs" role="status">{notice}</p>}
      </form>
    </Card>
  );
}

export function AcademicAssignmentsPage() {
  const { data, error, reload } = useODResource(API_ENDPOINTS.ADMIN.ACADEMICS);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold text-brand-dark">Demo Academic Assignments</h1>
      <p className="text-sm text-brand-muted">Class tutor changes apply to future OD applications.</p>
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {!data && !error && <p role="status" className="text-sm">Loading academic assignments…</p>}
      {data?.classes.map((item) => <ClassMapping key={item.id} item={item} onSave={reload} />)}
    </div>
  );
}
