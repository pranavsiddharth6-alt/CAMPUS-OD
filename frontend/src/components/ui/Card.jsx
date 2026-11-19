import React from 'react';

export function Card({
  title,
  subtitle,
  icon: Icon,
  action,
  children,
  footer,
  className = '',
  bodyClassName = '',
}) {
  return (
    <div className={`bg-white border border-brand-border rounded-lg shadow-sm ${className}`}>
      {(title || Icon || action) && (
        <div className="flex items-center justify-between px-5 py-4 border-b border-brand-border/70">
          <div className="flex items-center gap-3">
            {Icon && (
              <div className="p-2 bg-slate-50 text-brand-primary rounded-md border border-slate-200">
                <Icon className="w-4 h-4" />
              </div>
            )}
            <div>
              {title && <h3 className="text-sm font-semibold text-brand-dark tracking-tight">{title}</h3>}
              {subtitle && <p className="text-xs text-brand-muted mt-0.5">{subtitle}</p>}
            </div>
          </div>
          {action && <div>{action}</div>}
        </div>
      )}
      <div className={`p-5 ${bodyClassName}`}>{children}</div>
      {footer && (
        <div className="px-5 py-3 bg-slate-50 border-t border-brand-border/70 rounded-b-lg">
          {footer}
        </div>
      )}
    </div>
  );
}
