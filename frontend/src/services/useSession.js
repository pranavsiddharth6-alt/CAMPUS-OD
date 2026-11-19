import { useSyncExternalStore } from 'react';
import { getSession, subscribeSession } from './api';

export function useSession() {
  return useSyncExternalStore(subscribeSession, getSession);
}
