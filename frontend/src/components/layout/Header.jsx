import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Building2, LogOut, Menu, User } from 'lucide-react';
import { signOut } from '../../services/api';

export function Header({ currentRole, onToggleMobileSidebar, user }) {
  const navigate = useNavigate();

  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState('');

  const handleLogout = async () => {
    setSigningOut(true);
    setError('');
    try {
      await signOut();
      navigate('/login', { replace: true });
    } catch {
      setError('Sign-out failed. Try again.');
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <header className="bg-brand-primary text-white border-b border-brand-primary/80 sticky top-0 z-30 shadow-sm">
      <div className="px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Left: Mobile trigger & Institutional Branding */}
          <div className="flex items-center gap-3">
            {onToggleMobileSidebar && (
              <button
                type="button"
                onClick={onToggleMobileSidebar}
                className="p-1.5 rounded-md text-slate-300 hover:text-white hover:bg-white/10 md:hidden focus:outline-none focus:ring-2 focus:ring-white"
                aria-label="Toggle navigation menu"
              >
                <Menu className="w-5 h-5" />
              </button>
            )}

            <Link to="/" className="flex items-center gap-3 group">
              <div className="p-2 bg-white/10 rounded-md group-hover:bg-white/15 transition-colors">
                <Building2 className="w-5 h-5 text-white" />
              </div>
              <div className="flex flex-col">
                <span className="font-bold text-base tracking-tight leading-tight flex items-center gap-2">
                  Campus OD
                  <span className="text-[10px] uppercase font-semibold tracking-wider px-1.5 py-0.5 rounded bg-white/15 text-slate-200">
                    SKASC
                  </span>
                </span>
                <span className="text-[11px] text-slate-300 font-normal leading-tight hidden sm:block">
                  Sri Krishna Arts and Science College
                </span>
              </div>
            </Link>
          </div>

          {/* Right: Role indicator & Navigation items */}
          <div className="flex items-center gap-3">
            {currentRole ? (
              <div className="flex items-center gap-3">
                <div className="hidden sm:flex flex-col text-right">
                  <span className="text-xs font-medium text-white">
                    {user?.email}
                  </span>
                  <span className="text-[10px] text-slate-300 uppercase tracking-wider">
                    {currentRole} Portal
                  </span>
                </div>

                <div className="h-8 w-8 rounded-full bg-white/10 flex items-center justify-center text-white border border-white/20">
                  <User className="w-4 h-4" />
                </div>

                <button
                  type="button"
                  onClick={handleLogout}
                  disabled={signingOut}
                  title="Sign out"
                  aria-label="Sign out"
                  className="p-1.5 rounded-md text-slate-300 hover:text-white hover:bg-white/10 transition-colors focus:outline-none"
                >
                  <LogOut className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <Link
                to="/login"
                className="text-xs font-medium bg-white/10 hover:bg-white/20 text-white px-3 py-1.5 rounded-md border border-white/20 transition-colors"
              >
                Sign In
              </Link>
            )}
          </div>
        </div>
        {error && <p role="alert" className="pb-2 text-right text-xs text-white">{error}</p>}
      </div>
    </header>
  );
}
