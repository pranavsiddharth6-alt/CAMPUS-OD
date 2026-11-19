import React, { useEffect } from 'react';
import { BrowserRouter } from 'react-router-dom';
import { AppRoutes } from './routes';
import { restoreSession } from './services/api';

export default function App() {
  useEffect(() => {
    const restore = () => restoreSession().catch(() => {});
    restore();
    window.addEventListener('focus', restore);
    return () => window.removeEventListener('focus', restore);
  }, []);

  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
