import React, { useState } from 'react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Select } from '../../components/ui/Select';
import { Table, TableCell, TableRow } from '../../components/ui/Table';
import { API_ENDPOINTS, apiClient } from '../../services/api';
import { odError, useODResource } from '../../services/od';
import { AdminRecordFields, optionsFor, recordPayload } from './AdminRecordFields';

const kinds = { departments: 'Departments', 'academic-years': 'Academic years', classes: 'Classes' };

export function AdminCatalogPage() {
  const { data, error, reload } = useODResource(API_ENDPOINTS.ADMIN.CATALOG);
  const [kind, setKind] = useState('departments');
  const [record, setRecord] = useState(null);
  const [formVersion, setFormVersion] = useState(0);
  const [feedback, setFeedback] = useState(null);
  const [saving, setSaving] = useState(false);
  const fields = [{ name: 'name', label: 'Name', maxLength: kind === 'classes' ? 100 : kind === 'academic-years' ? 50 : 150 }];
  if (kind === 'departments') fields.push({ name: 'code', label: 'Code', maxLength: 20 });
  if (kind === 'classes') fields.push(
    { name: 'department_id', label: 'Department', locked: Boolean(record),
      options: optionsFor(data?.departments.filter((row) => row.is_active || row.id === record?.department_id)) },
    { name: 'academic_year_id', label: 'Academic year', locked: Boolean(record), options: optionsFor(data?.['academic-years']) },
    { name: 'batch', label: 'Batch', maxLength: 20 },
    { name: 'semester', label: 'Semester', type: 'number' },
    { name: 'section', label: 'Section', maxLength: 10 },
  );
  if (kind === 'academic-years') fields.push(
    { name: 'start_date', label: 'Start date', type: 'date' },
    { name: 'end_date', label: 'End date', type: 'date' },
    { name: 'is_current', label: 'Current academic year', type: 'checkbox' },
  );
  else fields.push({ name: 'is_active', label: 'Active', type: 'checkbox' });

  async function save(event) {
    event.preventDefault();
    setFeedback(null);
    setSaving(true);
    const payload = recordPayload(event.currentTarget, fields, record);
    try {
      await apiClient(API_ENDPOINTS.ADMIN.CATALOG + '/' + kind + (record ? '/' + record.id : ''), {
        method: record ? 'PUT' : 'POST', body: JSON.stringify(payload),
      });
      setRecord(null);
      setFormVersion((version) => version + 1);
      setFeedback({ message: 'Record saved.' });
      reload();
    } catch (failure) {
      setFeedback({ error: true, message: odError(failure, 'The academic record could not be saved.') });
    } finally {
      setSaving(false);
    }
  }

  return <div className="space-y-5">
    <h1 className="text-xl font-bold text-brand-dark">College Records</h1>
    {error && <p role="alert">{error}</p>}
    {feedback && <p role={feedback.error ? 'alert' : 'status'}>{feedback.message}</p>}
    {data && <>
      <Select label="Record type" value={kind} onChange={(event) => { setKind(event.target.value); setRecord(null); setFeedback(null); }}
        options={Object.entries(kinds).map(([value, label]) => ({ value, label }))} />
      <Card title={record ? 'Edit record' : 'Add record'}>
        <form key={(record?.id ?? kind) + formVersion} className="grid gap-4 sm:grid-cols-2" onSubmit={save}>
          <AdminRecordFields fields={fields} record={record ?? { is_active: true }} />
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={saving}>Save record</Button>
            {record && <Button variant="secondary" onClick={() => setRecord(null)}>Cancel</Button>}
          </div>
        </form>
      </Card>
      <Table headers={['Name', 'Details', 'Status', 'Actions']}>
        {data[kind].map((row) => <TableRow key={row.id}>
          <TableCell>{row.name}</TableCell>
          <TableCell>{row.code ?? (row.start_date ? row.start_date + ' to ' + row.end_date
            : [data.departments.find(({ id }) => id === row.department_id)?.name,
              data['academic-years'].find(({ id }) => id === row.academic_year_id)?.name, row.batch,
              'Semester ' + row.semester, 'Section ' + row.section].join(' · '))}</TableCell>
          <TableCell>{row.is_active === undefined ? (row.is_current ? 'Current' : 'Not current')
            : row.is_active ? 'Active' : 'Inactive'}</TableCell>
          <TableCell><Button size="sm" variant="secondary" onClick={() => { setRecord(row); setFeedback(null); }}>Edit</Button></TableCell>
        </TableRow>)}
      </Table>
    </>}
  </div>;
}
