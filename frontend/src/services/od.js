import { useEffect, useState } from 'react';
import { apiClient } from './api';

export const reviewable = new Set(['SUBMITTED', 'UNDER_TUTOR_REVIEW', 'UNDER_TUTOR_CORRECTION_REVIEW']);
export const evidenceOpen = new Set(['PRE_APPROVED', 'AWAITING_PARTICIPATION_PROOF', 'UNDER_FINAL_VERIFICATION', 'UNDER_TUTOR_CORRECTION_REVIEW']);

export const correctionRequested = new Set(['CORRECTION_REQUESTED', 'HOD_CORRECTION_REQUESTED']);

const statuses = {
  SUBMITTED: ['Submitted', 'primary'],
  UNDER_TUTOR_REVIEW: ['Under tutor review', 'warning'],
  CORRECTION_REQUESTED: ['Correction requested', 'warning'],
  PRE_APPROVED: ['Prior OD approved', 'success'],
  AWAITING_PARTICIPATION_PROOF: ['Awaiting participation evidence', 'warning'],
  UNDER_FINAL_VERIFICATION: ['Tutor evidence verification', 'primary'],
  UNDER_HOD_REVIEW: ['Awaiting HOD review', 'primary'],
  HOD_CORRECTION_REQUESTED: ['Correction after HOD review', 'warning'],
  UNDER_TUTOR_CORRECTION_REVIEW: ['Tutor reviewing corrections', 'warning'],
  OD_FINALIZED: ['OD finalized', 'success'],
  REJECTED: ['Rejected', 'danger'],
};

export const statusLabel = (status) => statuses[status]?.[0] ?? status.replaceAll('_', ' ').toLowerCase();
export const statusVariant = (status) => statuses[status]?.[1] ?? 'neutral';
export const dateRange = (app) => app.start_date === app.end_date ? app.start_date : `${app.start_date} to ${app.end_date}`;

export function odError(error, fallback) {
  return error.status && error.status !== 503 ? error.message : fallback;
}

export async function downloadODFile(endpoint, filename) {
  const blob = await apiClient(endpoint, { responseType: 'blob' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function viewODFile(endpoint) {
  const tab = window.open('about:blank', '_blank');
  if (!tab) throw new Error('The preview window was blocked.');
  tab.opener = null;
  try {
    const blob = await apiClient(endpoint, { responseType: 'blob' });
    if (tab.closed) return;
    const url = URL.createObjectURL(blob);
    tab.location.replace(url);
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
  } catch (error) {
    tab.close();
    throw error;
  }
}

export function useODResource(endpoint) {
  const [state, setState] = useState(null);
  const [request, setRequest] = useState(0);
  useEffect(() => {
    if (!endpoint) return;
    let active = true;
    apiClient(endpoint).then((data) => {
      if (active) setState({ endpoint, request, data, error: '' });
    }).catch((error) => {
      if (active) setState({ endpoint, request, data: null,
        error: odError(error, 'The OD service is temporarily unavailable.') });
    });
    return () => { active = false; };
  }, [endpoint, request]);

  return {
    ...(state && state.endpoint === endpoint ? state : { data: null, error: '' }),
    reload: () => setRequest((value) => value + 1),
  };
}
