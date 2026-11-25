import React, { useState } from 'react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Select } from '../../components/ui/Select';
import { Table, TableCell, TableRow } from '../../components/ui/Table';
import { API_ENDPOINTS, apiClient } from '../../services/api';
import { odError, useODResource } from '../../services/od';
import { AdminRecordFields, optionsFor, recordPayload } from './AdminRecordFields';

const roles = { student: 'Student', faculty: 'Faculty', hod: 'Head of Department', admin: 'Administrator' };
const roleKind = { STUDENT: 'student', TUTOR: 'faculty', HOD: 'hod', ADMIN: 'admin' };
const classifications = (items) => [{ value: '', label: 'Unclassified' },
  ...items.map(([value, label]) => ({ value, label }))];

export function AdminUsersPage() {
  const { data: users, error: usersError, reload } = useODResource(API_ENDPOINTS.ADMIN.USERS);
  const { data: catalog, error: catalogError } = useODResource(API_ENDPOINTS.ADMIN.CATALOG);
  const { data: roster } = useODResource(API_ENDPOINTS.ADMIN.DEMO_ROSTER);
  const [kind, setKind] = useState('student');
  const [editing, setEditing] = useState(null);
  const [enrolling, setEnrolling] = useState(null);
  const [prefill, setPrefill] = useState(null);
  const [department, setDepartment] = useState('');
  const [formVersion, setFormVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const departments = catalog?.departments ?? [];
  const classes = catalog?.classes ?? [];
  const fields = [{ name: 'full_name', label: 'Full name', maxLength: 150 }];
  if (!editing) fields.push({ name: 'email', label: 'Email', type: 'email', maxLength: 255 });
  if (kind === 'student') fields.push(
    { name: 'roll_number', label: 'Roll number', maxLength: 50 },
    { name: 'register_number', label: 'Register number', maxLength: 50 },
    { name: 'gender', label: 'Gender', optional: true, options: classifications([['MALE', 'Male'], ['FEMALE', 'Female']]) },
    { name: 'accommodation', label: 'Accommodation', optional: true, options: classifications([
      ['COLLEGE_HOSTEL', 'College Hostel'], ['OUTSIDE_STAYING', 'Outside Staying'], ['GUARDIAN', 'Guardian'], ['OTHER', 'Other'],
    ]) },
  );
  if (kind === 'faculty' || kind === 'admin') fields.push(
    { name: 'staff_id', label: 'Staff ID', maxLength: 50 },
    { name: 'designation', label: 'Designation', maxLength: 100 },
  );
  if (kind === 'faculty' || (!editing && (kind === 'hod' || kind === 'student'))) {
    fields.push({ name: 'department_id', label: 'Department',
      options: optionsFor(departments.filter((row) => row.is_active || row.id === editing?.department_id)) });
  }
  if (!editing && kind === 'student') fields.push({ name: 'class_id', label: 'Initial class',
    options: optionsFor(classes.filter((row) => row.is_active && row.department_id === department)) });

  function selectAccount(user, nextKind = 'student', defaultValues = null) {
    setEditing(user);
    setEnrolling(null);
    setKind(user ? roleKind[user.role] : nextKind);
    setPrefill(defaultValues);
    setDepartment(defaultValues?.department_id ?? '');
    setFormVersion((version) => version + 1);
    setError('');
  }

  async function save(endpoint, method, payload) {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await apiClient(endpoint, { method, ...(payload && { body: JSON.stringify(payload) }) });
      setNotice(result?.invitation_id
        ? (result.invitation_delivered
          ? 'Account created. Give the local operator this invitation ID: ' + result.invitation_id
          : 'Account created. The invitation could not be saved to the local outbox.')
        : 'Record saved.');
      selectAccount(null, kind);
      reload();
    } catch (failure) {
      setError(odError(failure, 'The college record could not be saved.'));
    } finally {
      setBusy(false);
    }
  }

  function saveAccount(event) {
    event.preventDefault();
    save(editing ? API_ENDPOINTS.ADMIN.ACCOUNT(editing.id) : API_ENDPOINTS.ADMIN.INVITE(kind),
      editing ? 'PUT' : 'POST', recordPayload(event.currentTarget, fields, editing));
  }

  const fixtures = roster ? [
    ['student', roster.students[0]], ['faculty', roster.tutors[0]], ['hod', roster.hods[0]],
  ] : [];

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-bold text-brand-dark">User Management</h1>
      {(error || usersError || catalogError) && <p role="alert" className="text-sm text-rose-700">{error || usersError || catalogError}</p>}
      {notice && <p role="status" className="break-words text-sm">{notice}</p>}
      {catalog && !enrolling && <Card title={editing ? 'Edit account' : 'Invite an account'}>
        {!editing && <div className="mb-4 flex flex-wrap items-end gap-2">
          <Select label="Account type" value={kind} onChange={(event) => selectAccount(null, event.target.value)}
            options={Object.entries(roles).map(([value, label]) => ({ value, label }))} />
          {fixtures.map(([type, fixture]) => fixture && <Button key={type} variant="secondary" size="sm"
            onClick={() => selectAccount(null, type, fixture)}>Fill demo {roles[type]}</Button>)}
        </div>}
        {editing && <p className="mb-3 text-sm">{editing.email}</p>}
        <form key={formVersion} className="grid gap-4 sm:grid-cols-2" onSubmit={saveAccount}
          onChange={(event) => { if (!editing && event.target.name === 'department_id') setDepartment(event.target.value); }}>
          <AdminRecordFields fields={fields} record={editing ?? prefill ?? {}} />
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={busy}>{editing ? 'Save account' : 'Create invitation'}</Button>
            {editing && <Button variant="secondary" onClick={() => selectAccount(null, kind)}>Cancel</Button>}
          </div>
        </form>
      </Card>}
      {enrolling && <Card title={'Enrollments · ' + enrolling.full_name}>
        <ul className="mb-4 space-y-2 text-sm">
          {enrolling.enrollments.map((row) => <li key={row.academic_year_id} className="flex items-center gap-3">
            <span>{classes.find(({ id }) => id === row.class_id)?.name} · {row.is_active ? 'Active' : 'Inactive'}</span>
            {row.is_active && <Button size="sm" variant="secondary" disabled={busy}
              onClick={() => save(API_ENDPOINTS.ADMIN.ENROLLMENT(enrolling.id), 'PUT', { class_id: row.class_id, is_active: false })}>End enrollment</Button>}
          </li>)}
        </ul>
        <form className="flex flex-wrap items-end gap-3" onSubmit={(event) => {
          event.preventDefault();
          const class_id = new FormData(event.currentTarget).get('class_id');
          save(API_ENDPOINTS.ADMIN.ENROLLMENT(enrolling.id), 'PUT', { class_id, is_active: true });
        }}>
          <Select label="Class" name="class_id" required options={optionsFor(classes.filter((row) => row.is_active))} />
          <Button type="submit" disabled={busy}>Save enrollment</Button>
          <Button variant="secondary" onClick={() => setEnrolling(null)}>Close</Button>
        </form>
      </Card>}
      {users && <Table headers={['Name', 'Role', 'Email', 'Status', 'Actions']}>
        {users.map((user) => <TableRow key={user.id}>
          <TableCell>{user.full_name || 'Unassigned'}</TableCell>
          <TableCell>{roles[roleKind[user.role]]}</TableCell>
          <TableCell>{user.email}</TableCell>
          <TableCell>{user.account_status.replaceAll('_', ' ').toLowerCase()}</TableCell>
          <TableCell><div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => selectAccount(user)}>Edit</Button>
            {user.enrollments && catalog && <Button variant="secondary" size="sm" onClick={() => { setEditing(null); setEnrolling(user); }}>
              Enrollments
            </Button>}
            {user.account_status !== 'DISABLED' && <Button variant="secondary" size="sm" disabled={busy}
              onClick={() => {
                if (window.confirm('Deactivate ' + user.email + '?'))
                  save(API_ENDPOINTS.ADMIN.ACCOUNT(user.id) + '/deactivate', 'POST');
              }}>Deactivate</Button>}
          </div></TableCell>
        </TableRow>)}
      </Table>}
    </div>
  );
}
