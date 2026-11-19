import React from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../../components/ui/Card';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Table, TableRow, TableCell } from '../../components/ui/Table';
import {
  ShieldCheck,
  Users,
  GraduationCap,
  Building2,
  FileCheck2,
  UserPlus,
  ArrowUpRight,
  BarChart3,
} from 'lucide-react';

export function AdminDashboardPage() {
  const stats = [
    { label: 'Enrolled Students', value: '3,840', icon: GraduationCap, variant: 'primary' },
    { label: 'Designated Class Tutors', value: '112', icon: Users, variant: 'secondary' },
    { label: 'Total OD Requests (Term)', value: '1,428', icon: FileCheck2, variant: 'default' },
    { label: 'Academic Departments', value: '18', icon: Building2, variant: 'success' },
  ];

  const departmentData = [
    {
      department: 'Computer Science & Applications',
      students: 420,
      tutors: 12,
      activeOds: 45,
      compliance: '98.2%',
    },
    {
      department: 'Commerce & Management',
      students: 650,
      tutors: 18,
      activeOds: 72,
      compliance: '96.5%',
    },
    {
      department: 'Biosciences & Biotechnology',
      students: 310,
      tutors: 9,
      activeOds: 28,
      compliance: '99.1%',
    },
    {
      department: 'Mathematics & Statistics',
      students: 240,
      tutors: 7,
      activeOds: 14,
      compliance: '97.8%',
    },
    {
      department: 'English & Foreign Languages',
      students: 190,
      tutors: 6,
      activeOds: 11,
      compliance: '100.0%',
    },
  ];

  return (
    <div className="space-y-6">
      {/* Admin Header */}
      <div className="bg-white border border-brand-border rounded-lg p-5 shadow-sm">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-slate-100 text-brand-primary rounded-lg border border-slate-200">
              <ShieldCheck className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-brand-dark">Institutional Administration</h1>
                <Badge variant="primary">Campus OD Master Control</Badge>
              </div>
              <p className="text-xs text-brand-muted mt-0.5">
                Sri Krishna Arts and Science College &bull; Academic Oversight &amp; Audit Governance
              </p>
            </div>
          </div>
          <div>
            <Link to="/admin/users">
              <Button icon={Users}>
                Manage System Users
              </Button>
            </Link>
          </div>
        </div>
      </div>

      <p className="text-xs text-brand-muted">
        Overview figures are sample data. User Management and Academic Assignments show the current demo records.
      </p>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, idx) => {
          const Icon = stat.icon;
          return (
            <Card key={idx} className="p-4" bodyClassName="p-0">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs text-brand-muted font-medium">{stat.label}</div>
                  <div className="text-2xl font-bold text-brand-dark mt-1">{stat.value}</div>
                </div>
                <div className="p-2.5 bg-slate-50 text-brand-primary rounded-md border border-slate-200">
                  <Icon className="w-5 h-5" />
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {/* Departmental OD Governance Table */}
      <Card
        title="Departmental On-Duty Oversight"
        subtitle="Summary of institutional OD volume and tutor assignment across departments"
        action={
          <Link to="/admin/users">
            <Button variant="ghost" size="sm">
              View User Directory
            </Button>
          </Link>
        }
      >
        <Table
          headers={[
            'Academic Department',
            'Enrolled Students',
            'Class Tutors',
            'Active Term ODs',
            'Proof Audit Compliance',
          ]}
        >
          {departmentData.map((dept, idx) => (
            <TableRow key={idx}>
              <TableCell className="font-semibold text-brand-dark">{dept.department}</TableCell>
              <TableCell>{dept.students}</TableCell>
              <TableCell>{dept.tutors}</TableCell>
              <TableCell className="font-medium text-brand-secondary">{dept.activeOds}</TableCell>
              <TableCell>
                <Badge variant="success">{dept.compliance}</Badge>
              </TableCell>
            </TableRow>
          ))}
        </Table>
      </Card>
    </div>
  );
}
