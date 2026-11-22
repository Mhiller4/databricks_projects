import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo } from 'react'
import { Circle, MapContainer, Marker, TileLayer, Tooltip, useMap } from 'react-leaflet'
import { T } from '../strings'
import type { Payload, Rec, Skipped } from '../types'

const pin = (cls: string, label = '') =>
  L.divIcon({ className: '', html: `<div class="mpin ${cls}">${label}</div>`, iconSize: [30, 30], iconAnchor: [15, 15] })

function Fit({ pts }: { pts: [number, number][] }) {
  const map = useMap()
  const key = JSON.stringify(pts)
  useEffect(() => {
    if (pts.length === 1) map.setView(pts[0], 12)
    else if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { padding: [40, 40], maxZoom: 13 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return null
}

export function CareMap({ payload, onMove, onPick }: {
  payload: Payload | null; onMove?: (p: { lat: number; lon: number }) => void; onPick?: (r: Rec) => void
}) {
  const ok = payload?.status === 'ok'
  const loc = ok ? (payload!.query.location as { lat: number; lon: number }) : null
  const recs: Rec[] = ok ? (payload!.recommendations?.length ? payload!.recommendations! : payload!.nearest_beyond_radius ?? []) : []
  const skipped: Skipped[] = ok ? payload!.skipped_nearby ?? [] : []
  const desert = ok ? payload!.medical_desert_alert : null
  const pts = useMemo<[number, number][]>(() => {
    const p: [number, number][] = []
    if (loc) p.push([loc.lat, loc.lon])
    recs.forEach((r) => p.push([r.lat, r.lon]))
    return p
  }, [loc, recs])

  return (
    <div className="card map-card">
      <MapContainer center={[22.5, 79]} zoom={5} scrollWheelZoom className="map" aria-label="Map of recommended facilities">
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                   url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        <Fit pts={pts} />
        {loc && desert?.triggered && (
          <Circle center={[loc.lat, loc.lon]} radius={desert.safe_km * 1000}
                  pathOptions={{ color: '#dc2626', weight: 2, dashArray: '6 6', fillOpacity: 0.04 }} />
        )}
        {skipped.map((s) => (
          <Marker key={`s-${s.facility_id}`} position={[s.lat, s.lon]} icon={pin(s.excluded ? 'mpin-skip' : 'mpin-lower', '–')}>
            <Tooltip>{s.name} · {s.distance_km} km<br />{s.reasons[0]}</Tooltip>
          </Marker>
        ))}
        {recs.map((r, i) => (
          <Marker key={`r-${r.facility_id}`} position={[r.lat, r.lon]} icon={pin('mpin-rec', String(i + 1))}
                  eventHandlers={{ click: () => onPick?.(r) }}>
            <Tooltip>{i + 1}. {r.name} · {r.distance_km} km · {r.confidence}</Tooltip>
          </Marker>
        ))}
        {loc && (
          <Marker position={[loc.lat, loc.lon]} icon={pin('mpin-you', '●')} draggable={!!onMove}
                  eventHandlers={{ dragend: (e) => { const p = (e.target as L.Marker).getLatLng(); onMove?.({ lat: p.lat, lon: p.lng }) } }}>
            <Tooltip>{(payload!.query.location as { display_name: string }).display_name}{onMove ? ` · ${T.pinDragHint}` : ''}</Tooltip>
          </Marker>
        )}
      </MapContainer>
      <div className="legend">
        <span><i className="dot dot-you" /> Patient</span>
        <span><i className="dot dot-rec" /> Recommended</span>
        <span><i className="dot dot-skip" /> Skipped (hover for why)</span>
        {desert?.triggered && <span><i className="dot dot-ring" /> Safe travel distance ({desert.safe_km} km)</span>}
      </div>
    </div>
  )
}
