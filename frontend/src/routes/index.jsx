import React from 'react';
import { Link, Routes, Route, Navigate } from 'react-router-dom';
import { PublicLayout } from '../components/layout/PublicLayout';
import { PortalLayout } from '../components/layout/PortalLayout';

import { LandingPage } from '../pages/LandingPage';
import { LoginPage } from '../pages/auth/LoginPage';
import { ActivationPage } from '../pages/auth/ActivationPage';
import { ApplicationDetailPage } from '../pages/ApplicationDetailPage';
import { portalPaths, restoreSession } from '../services/api';
import { useSession } from '../services/useSession';

import { StudentDashboardPage } from '../pages/student/StudentDashboardPage';
import { StudentApplicationsPage } from '../pages/student/StudentApplicationsPage';
import { NewApplicationPage } from '../pages/student/NewApplicationPage';

import { TutorDashboardPage } from '../pages/tutor/TutorDashboardPage';
import { TutorApplicationsPage } from '../pages/tutor/TutorApplicationsPage';

import { AdminDashboardPage } from '../pages/admin/AdminDashboardPage';
import { AdminUsersPage } from '../pages/admin/AdminUsersPage';
import { AcademicAssignmentsPage } from '../pages/admin/AcademicAssignmentsPage';

function ProtectedPortal({ role }) {
  const { state, user } = useSession();
  if (state === 'loading') return <p className="p-6" role="status">Checking your session…</p>;
  if (state === 'unavailable' || state === 'blocked') {
    return (
      <div className="space-y-3 p-6">
        <p role="alert">
          {state === 'blocked'
            ? 'The server blocked the session check. For the local demo, use http://localhost:5173.'
            : 'The session service is temporarily unavailable. Check that the backend is running.'}
        </p>
        <div className="flex gap-4">
          <button type="button" className="underline" onClick={() => restoreSession().catch(() => {})}>Try again</button>
          <Link className="underline" to="/login">Go to sign in</Link>
        </div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== role) return <Navigate to={portalPaths[user.role]} replace />;
  return <PortalLayout role={user.role.toLowerCase()} user={user} />;
}

export function AppRoutes() {
  return (
    <Routes>
      {/* Public Pages */}
      <Route element={<PublicLayout />}>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/activate" element={<ActivationPage />} />
      </Route>

      {/* Student Portal Routes */}
      <Route path="/student" element={<ProtectedPortal role="STUDENT" />}>
        <Route index element={<Navigate to="/student/dashboard" replace />} />
        <Route path="dashboard" element={<StudentDashboardPage />} />
        <Route path="applications" element={<StudentApplicationsPage />} />
        <Route path="applications/new" element={<NewApplicationPage />} />
        <Route path="applications/:applicationId" element={<ApplicationDetailPage />} />
        <Route path="applications/:applicationId/correct" element={<NewApplicationPage />} />
      </Route>

      {/* Tutor Portal Routes */}
      <Route path="/tutor" element={<ProtectedPortal role="TUTOR" />}>
        <Route index element={<Navigate to="/tutor/dashboard" replace />} />
        <Route path="dashboard" element={<TutorDashboardPage />} />
        <Route path="applications" element={<TutorApplicationsPage />} />
        <Route path="applications/:applicationId" element={<ApplicationDetailPage tutor />} />
      </Route>

      {/* Admin Portal Routes */}
      <Route path="/admin" element={<ProtectedPortal role="ADMIN" />}>
        <Route index element={<Navigate to="/admin/dashboard" replace />} />
        <Route path="dashboard" element={<AdminDashboardPage />} />
        <Route path="users" element={<AdminUsersPage />} />
        <Route path="academics" element={<AcademicAssignmentsPage />} />
      </Route>

      {/* Fallback route */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
