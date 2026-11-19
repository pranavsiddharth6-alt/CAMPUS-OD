import React from 'react';

export function Table({ headers = [], children, emptyMessage = 'No records found.', isEmpty = false }) {
  return (
    <div className="overflow-x-auto border border-brand-border rounded-lg bg-white shadow-sm">
      <table className="min-w-full divide-y divide-brand-border text-left text-sm">
        <thead className="bg-slate-50 text-xs font-semibold text-brand-muted uppercase tracking-wider">
          <tr>
            {headers.map((head, idx) => (
              <th key={idx} scope="col" className="px-4 py-3">
                {head}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 text-slate-700">
          {isEmpty ? (
            <tr>
              <td colSpan={headers.length || 1} className="px-4 py-8 text-center text-xs text-slate-400">
                {emptyMessage}
              </td>
            </tr>
          ) : (
            children
          )}
        </tbody>
      </table>
    </div>
  );
}

export function TableRow({ children, className = '', onClick }) {
  return (
    <tr
      onClick={onClick}
      className={`hover:bg-slate-50/80 transition-colors ${onClick ? 'cursor-pointer' : ''} ${className}`}
    >
      {children}
    </tr>
  );
}

export function TableCell({ children, className = '' }) {
  return <td className={`px-4 py-3 whitespace-nowrap text-xs sm:text-sm ${className}`}>{children}</td>;
}
