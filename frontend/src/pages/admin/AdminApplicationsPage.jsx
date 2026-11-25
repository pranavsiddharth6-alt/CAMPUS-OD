import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Table, TableCell, TableRow } from '../../components/ui/Table';
import { API_ENDPOINTS } from '../../services/api';
import { dateRange, statusLabel, statusVariant, useODResource } from '../../services/od';

export function AdminApplicationsPage() {
  const [offset, setOffset] = useState(0);
  const { data, error } = useODResource(API_ENDPOINTS.ADMIN.APPLICATIONS + '?offset=' + offset);
  return <div className="space-y-5">
    <h1 className="text-xl font-bold text-brand-dark">OD Monitoring</h1>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">Loading applications…</p>}
    {data && <Table headers={['Application', 'Student', 'Event', 'Dates', 'Assigned tutor', 'Status', 'Actions']}>
      {data.map((app) => <TableRow key={app.id}>
        <TableCell>{app.application_number}</TableCell>
        <TableCell>{app.student_name} ({app.student_roll_number})</TableCell>
        <TableCell>{app.event_name}</TableCell>
        <TableCell>{dateRange(app)}</TableCell>
        <TableCell>{app.tutor_name}</TableCell>
        <TableCell><Badge variant={statusVariant(app.status)}>{statusLabel(app.status)}</Badge></TableCell>
        <TableCell><Link className="text-brand-primary underline" to={'/admin/applications/' + app.id}>View</Link></TableCell>
      </TableRow>)}
    </Table>}
    {data?.length === 0 && <p className="text-sm">No applications on this page.</p>}
    <div className="flex gap-2">
      <Button variant="secondary" disabled={!offset} onClick={() => setOffset(offset - 50)}>Previous</Button>
      <Button variant="secondary" disabled={data?.length !== 50} onClick={() => setOffset(offset + 50)}>Next</Button>
    </div>
  </div>;
}
