import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useMemo } from 'react'
import { Circle, MapContainer, Marker, Tooltip, TileLayer, useMap } from 'react-leaflet'
import { T } from '../strings'
import type { Payload, Rec, Skipped } from '../types'

const pin = (cls: string, label = '', size = 30) =>
  L.divIcon({
    className: '',
    html: `<div class="mpin ${cls}">${label}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  })

function Fit({ pts }: { pts: [number, number][] }) {
  const map = useMap()
  const key = JSON.stringify(pts)
  useEffect(() => {
    if (pts.length === 1) map.setView(pts[0], 12)
    else if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { padding: [44, 44], maxZoom: 13 })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return null
}

function FocusSelected({ rec }: { rec: Rec | null }) {
  const map = useMap()
  useEffect(() => {
    if (!rec) return
    const cur = map.getBounds()
    if (!cur.contains([rec.lat, rec.lon])) {
      map.panTo([rec.lat, rec.lon], { animate: true, duration: 0.35 })
    }
  }, [map, rec])
  return null
}

export function CareMap({
  payload,
  selectedId,
  onSelect,
  onMove,
  onPick,
  showSkipped = true,
}: {
  payload: Payload | null
  selectedId?: string | null
  onSelect?: (r: Rec) => void
  onMove?: (p: { lat: number; lon: number }) => void
  onPick?: (r: Rec) => void
  showSkipped?: boolean
}) {
  const ok = payload?.status === 'ok'
  const loc = ok ? (payload!.query.location as { lat: number; lon: number; display_name: string }) : null
  const recs = useMemo<Rec[]>(
    () =>
      ok
        ? payload!.recommendations?.length
          ? payload!.recommendations!
          : payload!.nearest_beyond_radius ?? []
        : [],
    [ok, payload],
  )
  const skipped: Skipped[] = ok && showSkipped ? payload!.skipped_nearby ?? [] : []
  const desert = ok ? payload!.medical_desert_alert : null

  const pts = useMemo<[number, number][]>(() => {
    const p: [number, number][] = []
    if (loc) p.push([loc.lat, loc.lon])
    recs.forEach((r) => p.push([r.lat, r.lon]))
    return p
  }, [loc, recs])

  const selectedRec = useMemo(
    () => recs.find((r) => r.facility_id === selectedId) ?? null,
    [recs, selectedId],
  )

  return (
    <div className="map-card">
      <MapContainer
        center={[22.5, 79]}
        zoom={5}
        scrollWheelZoom
        className="map"
        aria-label="Map of recommended facilities"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Fit pts={pts} />
        <FocusSelected rec={selectedRec} />

        {loc && desert?.triggered && (
          <Circle
            center={[loc.lat, loc.lon]}
            radius={desert.safe_km * 1000}
            pathOptions={{ color: '#C81E1E', weight: 2, dashArray: '6 6', fillOpacity: 0.05 }}
          />
        )}

        {skipped.map((s) => (
          <Marker
            key={`s-${s.facility_id}`}
            position={[s.lat, s.lon]}
            icon={pin(s.excluded ? 'mpin-skip' : 'mpin-lower', '–', 22)}
          >
            <Tooltip>
              <strong>{s.name}</strong> · {s.distance_km} km
              <br />
              {s.reasons[0]}
            </Tooltip>
          </Marker>
        ))}

        {recs.map((r, i) => {
          const active = r.facility_id === selectedId
          return (
            <Marker
              key={`r-${r.facility_id}`}
              position={[r.lat, r.lon]}
              zIndexOffset={active ? 600 : 100 - i}
              icon={pin(active ? 'mpin-rec mpin-active' : 'mpin-rec', String(i + 1), active ? 34 : 30)}
              eventHandlers={{
                click: () => {
                  onSelect?.(r)
                  onPick?.(r)
                },
              }}
            >
              <Tooltip>
                <strong>
                  {i + 1}. {r.name}
                </strong>
                <br />
                {r.distance_km} km · {r.confidence} confidence
              </Tooltip>
            </Marker>
          )
        })}

        {loc && (
          <Marker
            position={[loc.lat, loc.lon]}
            zIndexOffset={500}
            icon={pin('mpin-you', '●', 26)}
            draggable={!!onMove}
            eventHandlers={{
              dragend: (e) => {
                const p = (e.target as L.Marker).getLatLng()
                onMove?.({ lat: p.lat, lon: p.lng })
              },
            }}
          >
            <Tooltip>
              <strong>{loc.display_name.replace(' (post office)', '')}</strong>
              {onMove ? ` · ${T.pinDragHint}` : ''}
            </Tooltip>
          </Marker>
        )}
      </MapContainer>

      <div className="legend">
        <span>
          <i className="dot dot-you" /> Patient{onMove ? ' (drag pin)' : ''}
        </span>
        <span>
          <i className="dot dot-rec" /> Verified ({recs.length})
        </span>
        {showSkipped && skipped.length > 0 && (
          <span>
            <i className="dot dot-skip" /> Skipped ({skipped.length})
          </span>
        )}
        {desert?.triggered && (
          <span>
            <i className="dot dot-ring" /> Safe range ({desert.safe_km} km)
          </span>
        )}
      </div>
    </div>
  )
}
