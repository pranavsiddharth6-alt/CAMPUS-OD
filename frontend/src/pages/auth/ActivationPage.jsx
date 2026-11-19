import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '../../components/ui/Button';
import { Card } from '../../components/ui/Card';
import { Input } from '../../components/ui/Input';
import { activateAccount } from '../../services/api';

export function ActivationPage() {
  const navigate = useNavigate();
  const [invitation, setInvitation] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function handleSubmit(event) {
    event.preventDefault();
    if (password !== confirmation) {
      setError('Passwords do not match.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await activateAccount(invitation.trim(), password);
      setInvitation('');
      navigate('/login', { replace: true });
    } catch (failure) {
      setError(failure.status === 400 ? 'This invitation or password is invalid.' :
        failure.status === 429 ? 'Too many attempts. Try again later.' : 'Activation is temporarily unavailable.');
    } finally {
      setPassword('');
      setConfirmation('');
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-md mx-auto my-auto py-6">
      <h1 className="mb-4 text-center text-xl font-bold text-brand-primary">Activate an invited account</h1>
      <Card>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <Input label="Invitation code" type="password" autoComplete="off" value={invitation}
            onChange={(event) => setInvitation(event.target.value)} required />
          <Input label="New password" type="password" autoComplete="new-password" value={password}
            minLength={15} maxLength={1024} helperText="Use at least 15 characters."
            onChange={(event) => setPassword(event.target.value)} required />
          <Input label="Confirm password" type="password" autoComplete="new-password" value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)} required />
          {error && <p role="alert" className="text-xs text-rose-700">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy}>{busy ? 'Activating…' : 'Activate Account'}</Button>
          <Link to="/login" className="block text-center text-xs text-brand-secondary hover:underline">Back to sign in</Link>
        </form>
      </Card>
    </div>
  );
}
