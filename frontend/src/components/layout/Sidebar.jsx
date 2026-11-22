import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  FileText,
  PlusCircle,
  CheckSquare,
  Users,
  BookOpen,
  ChevronRight,
} from 'lucide-react';

export function Sidebar({ role = 'student', isOpen, onClose }) {
  const navItems = {
    student: [
      {
        name: 'Dashboard',
        to: '/student/dashboard',
        icon: LayoutDashboard,
      },
      {
        name: 'My Applications',
        to: '/student/applications',
        icon: FileText,
      },
      {
        name: 'Apply for OD',
        to: '/student/applications/new',
        icon: PlusCircle,
      },
    ],
    tutor: [
      {
        name: 'Tutor Dashboard',
        to: '/tutor/dashboard',
        icon: LayoutDashboard,
      },
      {
        name: 'OD Verifications',
        to: '/tutor/applications',
        icon: CheckSquare,
      },
    ],
    hod: [
      { name: 'HOD Dashboard', to: '/hod/dashboard', icon: LayoutDashboard },
      { name: 'Pending Requests', to: '/hod/applications', icon: CheckSquare },
      { name: 'Decision History', to: '/hod/history', icon: FileText },
    ],
    admin: [
      {
        name: 'Admin Overview',
        to: '/admin/dashboard',
        icon: LayoutDashboard,
      },
      {
        name: 'User Management',
        to: '/admin/users',
        icon: Users,
      },
      {
        name: 'Academic Assignments',
        to: '/admin/academics',
        icon: BookOpen,
      },
    ],
  };

  const currentItems = navItems[role] || navItems.student;

  const roleLabels = {
    student: 'Student Workspace',
    tutor: 'Class Tutor Workspace',
    hod: 'Head of Department Workspace',
    admin: 'Institutional Administration',
  };

  return (
    <>
      {/* Mobile backdrop */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 z-40 bg-slate-900/40 backdrop-blur-xs md:hidden"
          aria-hidden="true"
        />
      )}

      {/* Sidebar container */}
      <aside
        className={`fixed top-16 bottom-0 left-0 z-40 w-64 bg-white border-r border-brand-border flex flex-col transition-transform duration-200 ease-in-out md:translate-x-0 ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Workspace section header */}
        <div className="p-4 border-b border-brand-border/60 bg-slate-50/50">
          <div className="text-[11px] font-semibold text-brand-muted uppercase tracking-wider">
            Workspace
          </div>
          <div className="text-xs font-semibold text-brand-dark mt-0.5 truncate">
            {roleLabels[role]}
          </div>
        </div>

        {/* Navigation links */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {currentItems.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to.endsWith('dashboard')}
                onClick={onClose}
                className={({ isActive }) =>
                  `flex items-center gap-3 px-3 py-2 rounded-md text-xs font-medium transition-colors ${
                    isActive
                      ? 'bg-blue-50 text-brand-primary border border-blue-200 font-semibold shadow-xs'
                      : 'text-slate-600 hover:text-brand-dark hover:bg-slate-50 border border-transparent'
                  }`
                }
              >
                <Icon className="w-4 h-4 shrink-0" />
                <span className="flex-1 truncate">{item.name}</span>
                <ChevronRight className="w-3.5 h-3.5 text-slate-400 opacity-60" />
              </NavLink>
            );
          })}
        </nav>

        {/* Institutional notice */}
        <div className="px-3 py-2.5 border-t border-brand-border/60 text-[10px] text-brand-muted text-center bg-white">
          Sri Krishna Arts and Science College
        </div>
      </aside>
    </>
  );
}
