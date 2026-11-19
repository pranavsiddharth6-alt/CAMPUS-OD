import React, { useState } from 'react';
import { Link, Navigate } from 'react-router-dom';
import { Building2, Lock, Mail } from 'lucide-react';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { portalPaths, signIn } from '../../services/api';
import { useSession } from '../../services/useSession';

export function LoginPage() {
  const { state, user } = useSession();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      await signIn(email, password);
    } catch (failure) {
      setError(failure.status === 401 ? 'Invalid email or password.' :
        failure.status === 429 ? 'Too many attempts. Try again later.' : 'Sign-in is temporarily unavailable.');
    } finally {
      setPassword('');
      setBusy(false);
    }
  }

  if (user) return <Navigate to={portalPaths[user.role]} replace />;

  return (
    <div className="w-full max-w-md mx-auto my-auto py-6">
      <div className="text-center mb-6">
        <div className="inline-flex p-2.5 bg-brand-primary text-white rounded-lg shadow-sm mb-3">
          <Building2 className="w-6 h-6" />
        </div>
        <h1 className="text-xl font-bold text-brand-primary">Campus OD Portal Login</h1>
        <p className="text-xs text-brand-muted mt-1">Sri Krishna Arts and Science College (SKASC)</p>
      </div>
      <Card title="Sign In with College Credentials" className="shadow-sm">
        <form onSubmit={handleSubmit} className="space-y-4">
          <Input label="College email" type="email" icon={Mail} value={email} autoComplete="username"
            onChange={(event) => setEmail(event.target.value)} required />
          <Input label="Password" type="password" icon={Lock} value={password} autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)} required />
          {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy || state === 'loading'}>
            {busy ? 'Signing in…' : 'Sign In'}
          </Button>
          <Link to="/activate" className="block text-center text-xs text-brand-secondary hover:underline">
            Activate an invited account
          </Link>
        </form>
      </Card>
    </div>
  );
}
