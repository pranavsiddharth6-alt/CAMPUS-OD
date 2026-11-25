import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { MapODPanel } from '../../components/od/MapODPanel';

export function MapODPage() {
  const { applicationId } = useParams();
  return (
    <div className="max-w-4xl space-y-4">
      <Link className="text-sm text-brand-primary underline" to="/student/post-od">Back to Post OD</Link>
      <h1 className="text-xl font-bold text-brand-dark">Event-day location</h1>
      <MapODPanel key={applicationId} applicationId={applicationId} />
    </div>
  );
}
