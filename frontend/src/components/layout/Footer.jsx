import React from 'react';

export function Footer() {
  return (
    <footer className="bg-white border-t border-brand-border py-4 mt-auto">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between text-xs text-brand-muted gap-2">
        <div>
          &copy; {new Date().getFullYear()} Sri Krishna Arts and Science College (SKASC). All rights reserved.
        </div>
        <div>
          Campus OD &bull; Smart On-Duty Management System
        </div>
      </div>
    </footer>
  );
}
