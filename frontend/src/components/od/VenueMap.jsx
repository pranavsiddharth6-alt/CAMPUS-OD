import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Button } from '../ui/Button';
import { Input } from '../ui/Input';

const osmAttribution = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
const tileUrl = import.meta.env.VITE_MAP_OD_TILE_URL ?? (import.meta.env.DEV ? 'https://tile.openstreetmap.org/{z}/{x}/{y}.png' : '');
const tileAttribution = import.meta.env.VITE_MAP_OD_TILE_ATTRIBUTION ?? osmAttribution;
const point = ({ latitude, longitude }) => [latitude, longitude];

export function VenueMap({ venue, capture, radius, onPick, basemap = false }) {
  const container = useRef(null);
  const mapRef = useRef(null);
  const layersRef = useRef(null);
  const onPickRef = useRef(onPick);
  const [tileState, setTileState] = useState(basemap && tileUrl ? 'loading' : '');
  const editable = Boolean(onPick);

  useEffect(() => { onPickRef.current = onPick; }, [onPick]);

  useEffect(() => {
    const map = L.map(container.current, { scrollWheelZoom: false, maxZoom: 19 }).setView([11.0168, 76.9558], 12);
    mapRef.current = map;
    layersRef.current = L.layerGroup().addTo(map);
    if (editable) {
      map.on('click', ({ latlng }) => {
        const location = latlng.wrap();
        onPickRef.current?.({ latitude: location.lat, longitude: location.lng });
      });
    }
    if (basemap && tileUrl) {
      L.tileLayer(tileUrl, { attribution: tileAttribution, maxZoom: 19, maxNativeZoom: 19 })
        .on('tileerror', () => setTileState('error'))
        .on('load', () => setTileState((state) => state === 'error' ? state : 'ready'))
        .addTo(map);
    }
    const resize = new ResizeObserver(() => map.invalidateSize({ pan: false }));
    resize.observe(container.current);
    return () => {
      resize.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, [basemap, editable]);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    layers.clearLayers();
    if (!venue) return;
    const approved = L.latLng(point(venue));
    let boundary;
    if (radius) {
      boundary = L.circle(approved, { radius, color: '#1d4e89', weight: 2, fillOpacity: 0.09, interactive: false }).addTo(layers);
    }
    L.circleMarker(approved, { radius: 8, color: '#163760', fillOpacity: 1, interactive: false }).addTo(layers);
    if (capture) {
      const student = L.latLng(point(capture));
      student.lng += 360 * Math.round((approved.lng - student.lng) / 360);
      L.circleMarker(student, { radius: 5, color: '#ffffff', weight: 2,
        fillColor: '#a54b0b', fillOpacity: 1, interactive: false }).addTo(layers);
      const bounds = boundary?.getBounds() ?? L.latLngBounds([approved]);
      map.fitBounds(bounds.extend(student), { padding: [24, 24], maxZoom: 17 });
    } else if (boundary) {
      map.fitBounds(boundary.getBounds(), { padding: [24, 24], maxZoom: 17 });
    } else {
      map.setView(approved, editable ? map.getZoom() : 15);
    }
  }, [venue, capture, radius, editable]);

  return (
    <div className="space-y-2">
      <div ref={container} role="region" aria-label={editable ? 'Select the expected venue on the map' : 'Venue and capture map'}
        className="relative isolate h-64 w-full rounded-md border border-brand-border !bg-slate-100 sm:h-80" />
      {tileState === 'loading' && <p role="status" className="text-xs text-brand-muted">Loading map tiles…</p>}
      {tileState === 'error' && <p role="status" className="text-xs text-brand-muted">Map tiles are unavailable. Coordinates and location markers are still available.</p>}
      {basemap && !tileUrl && <p className="text-xs text-brand-muted">Basemap tiles are disabled. You can enter the venue coordinates.</p>}
      {venue && <p className="text-xs text-brand-muted">Navy marker · Expected venue{capture ? ' · Orange marker · Student capture' : ''}</p>}
    </div>
  );
}

export function VenuePinField({ value, onChange, locked = false }) {
  const [latitude, setLatitude] = useState(value?.latitude ?? '');
  const [longitude, setLongitude] = useState(value?.longitude ?? '');
  const [error, setError] = useState('');
  function pick(location) {
    setLatitude(location.latitude);
    setLongitude(location.longitude);
    setError('');
    onChange(location);
  }
  function useCoordinates() {
    const lat = Number(latitude);
    const lon = Number(longitude);
    if (latitude === '' || longitude === '' || !Number.isFinite(lat) || !Number.isFinite(lon) ||
        Math.abs(lat) > 90 || Math.abs(lon) > 180) {
      setError('Enter latitude from −90 to 90 and longitude from −180 to 180.');
      return;
    }
    pick({ latitude: lat, longitude: lon });
  }
  return (
    <div className="space-y-3">
      {!locked && <p className="text-sm text-brand-muted">Select the event venue on the map, or enter its coordinates. You can move the pin before submitting.</p>}
      {(!locked || value) && <VenueMap venue={value} basemap onPick={locked ? undefined : pick} />}
      {value && <p className="text-sm text-brand-dark">Expected venue pin · {value.latitude.toFixed(6)}, {value.longitude.toFixed(6)}</p>}
      {!locked && <div className="grid items-end gap-2 sm:grid-cols-[1fr_1fr_auto]">
        <Input label="Venue latitude" type="number" step="any" value={latitude} onChange={(event) => setLatitude(event.target.value)} />
        <Input label="Venue longitude" type="number" step="any" value={longitude} onChange={(event) => setLongitude(event.target.value)} />
        <Button variant="secondary" onClick={useCoordinates}>Use coordinates</Button>
      </div>}
      {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
      {locked && !value && <p className="text-sm text-brand-muted">No venue pin is available for this legacy application.</p>}
    </div>
  );
}
