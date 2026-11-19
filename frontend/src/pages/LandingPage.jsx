import React from 'react';
import { Link } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { Button } from '../components/ui/Button';
import {
  GraduationCap,
  UserCheck,
  ShieldCheck,
  FileCheck2,
  MapPin,
  Clock,
  ArrowRight,
  Building2,
} from 'lucide-react';

export function LandingPage() {
  return (
    <div className="w-full max-w-5xl mx-auto space-y-8 py-6">
      {/* Institutional Hero Banner */}
      <div className="bg-white border border-brand-border rounded-xl p-6 sm:p-10 shadow-sm text-center">
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-50 text-brand-primary text-xs font-semibold border border-blue-200 mb-4">
          <Building2 className="w-3.5 h-3.5" />
          Sri Krishna Arts and Science College (SKASC)
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold text-brand-primary tracking-tight">
          Campus OD
        </h1>
        <p className="text-base sm:text-lg text-brand-secondary font-medium mt-1">
          Smart On-Duty Management System
        </p>
        <p className="text-xs sm:text-sm text-brand-muted max-w-2xl mx-auto mt-3 leading-relaxed">
          The centralized institutional portal for submitting, verifying, and tracking official
          college on-duty permissions with tutor endorsements and event evidence.
        </p>

        <div className="flex flex-wrap items-center justify-center gap-3 mt-6">
          <Link to="/login">
            <Button size="lg" icon={ArrowRight}>
              Access College Portal
            </Button>
          </Link>
          <Link to="/student/dashboard">
            <Button variant="secondary" size="lg">
              Explore Demo Portals
            </Button>
          </Link>
        </div>
      </div>

      {/* Role Gateways */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Student Gateway */}
        <Card
          title="Student Portal"
          subtitle="OD applications & tracking"
          icon={GraduationCap}
          footer={
            <Link to="/student/dashboard">
              <Button variant="outline" size="sm" className="w-full justify-between">
                <span>Enter Student Portal</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Button>
            </Link>
          }
        >
          <ul className="text-xs text-slate-600 space-y-2">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Submit multi-day OD requests
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Attach original college OD form
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Submit event verification proof
            </li>
          </ul>
        </Card>

        {/* Tutor Gateway */}
        <Card
          title="Class Tutor Portal"
          subtitle="Verification & endorsement"
          icon={UserCheck}
          footer={
            <Link to="/tutor/dashboard">
              <Button variant="outline" size="sm" className="w-full justify-between">
                <span>Enter Tutor Portal</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Button>
            </Link>
          }
        >
          <ul className="text-xs text-slate-600 space-y-2">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Automated class student routing
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Preliminary event permission review
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Final proof audit &amp; approval
            </li>
          </ul>
        </Card>

        {/* Admin Gateway */}
        <Card
          title="Institutional Admin"
          subtitle="Departmental governance"
          icon={ShieldCheck}
          footer={
            <Link to="/admin/dashboard">
              <Button variant="outline" size="sm" className="w-full justify-between">
                <span>Enter Admin Portal</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </Button>
            </Link>
          }
        >
          <ul className="text-xs text-slate-600 space-y-2">
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              College-wide OD activity logs
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Department &amp; class tutor mapping
            </li>
            <li className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-brand-secondary" />
              Institutional audit reports
            </li>
          </ul>
        </Card>
      </div>

      {/* Institutional Workflow Steps */}
      <div className="bg-white border border-brand-border rounded-lg p-6 shadow-sm">
        <h3 className="text-sm font-bold text-brand-primary uppercase tracking-wider mb-4">
          Institutional OD Workflow Protocol
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 text-xs text-slate-600">
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-md">
            <div className="font-semibold text-brand-dark mb-1">1. Student Application</div>
            Student submits request with event details and uploads original college form.
          </div>
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-md">
            <div className="font-semibold text-brand-dark mb-1">2. Tutor Preliminary Review</div>
            Assigned class tutor verifies eligibility and grants preliminary endorsement.
          </div>
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-md">
            <div className="font-semibold text-brand-dark mb-1">3. Event Proof Submission</div>
            Student submits GPS map camera photo and organizer attendance proof.
          </div>
          <div className="p-3 bg-slate-50 border border-slate-200 rounded-md">
            <div className="font-semibold text-brand-dark mb-1">4. Final Verification</div>
            Tutor validates submitted proof for final institutional attendance credit.
          </div>
        </div>
      </div>
    </div>
  );
}
