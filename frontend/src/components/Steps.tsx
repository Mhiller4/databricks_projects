import { useState } from 'react'
import { GROUP_ORDER, SERVICE_INFO } from '../services'
import type { Role, Service } from '../types'
import { LocationBox, type LocValue } from './LocationBox'

export function WhoStep({ onPick }: { onPick: (r: Role) => void }) {
  return (
    <section className="step" aria-labelledby="who-h">
      <h2 id="who-h" className="step-q">Who is looking for care?</h2>
      <div className="big-choices">
        <button className="big-choice" onClick={() => onPick('patient')}>
          <span className="big-icon" aria-hidden="true">🧑‍🤝‍🧑</span>
          <span><strong>Patient or family</strong><span className="muted">For yourself or someone you care for</span></span>
        </button>
        <button className="big-choice" onClick={() => onPick('provider')}>
          <span className="big-icon" aria-hidden="true">🩺</span>
          <span><strong>Health worker</strong><span className="muted">ASHA, nurse, doctor, NGO or clinic staff</span></span>
        </button>
      </div>
    </section>
  )
}

export function EmergencyStep({ onAnswer }: { onAnswer: (emergency: boolean) => void }) {
  return (
    <section className="step" aria-labelledby="em-h">
      <h2 id="em-h" className="step-q">Is this an emergency right now?</h2>
      <p className="muted">Heavy bleeding, unconscious, trouble breathing, severe pain in pregnancy, or a bad accident.</p>
      <a className="call-108" href="tel:108">📞 Call 108 ambulance</a>
      <div className="big-choices two">
        <button className="big-choice danger" onClick={() => onAnswer(true)}><strong>Yes, it's urgent</strong><span className="muted">Find the closest care that can help now</span></button>
        <button className="big-choice" onClick={() => onAnswer(false)}><strong>No, not urgent</strong><span className="muted">Find the best place nearby</span></button>
      </div>
    </section>
  )
}

export function CareStep({ services, onPick }: { services: Service[]; onPick: (key: string) => void }) {
  const [filter, setFilter] = useState('')
  const known = new Set(services.map((s) => s.key))
  const f = filter.trim().toLowerCase()
  const match = (key: string) => {
    if (!f) return true
    const s = services.find((x) => x.key === key)
    const i = SERVICE_INFO[key]
    return [i?.name, i?.hint, s?.label, ...(s?.synonyms ?? [])].some((t) => t?.toLowerCase().includes(f))
  }
  return (
    <section className="step" aria-labelledby="care-h">
      <h2 id="care-h" className="step-q">What care is needed?</h2>
      <input className="filter" placeholder="Search, e.g. kidney, baby, scan…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter services" />
      {GROUP_ORDER.map((g) => {
        const keys = Object.entries(SERVICE_INFO).filter(([k, v]) => v.group === g && known.has(k) && match(k)).map(([k]) => k)
        if (!keys.length) return null
        return (
          <div key={g} className="svc-group">
            <h3 className="group-h">{g}</h3>
            <div className="svc-grid">
              {keys.map((k) => (
                <button key={k} className="svc" onClick={() => onPick(k)}>
                  <span className="svc-icon" aria-hidden="true">{SERVICE_INFO[k].icon}</span>
                  <strong>{SERVICE_INFO[k].name}</strong>
                  <span className="muted small">{SERVICE_INFO[k].hint}</span>
                </button>
              ))}
            </div>
          </div>
        )
      })}
    </section>
  )
}

export function WhereStep({ loc, onLoc, onGo, urgency, onUrgency, showUrgency, busy }: {
  loc: LocValue; onLoc: (v: LocValue) => void; onGo: (override?: LocValue) => void
  urgency: 'routine' | 'emergency'; onUrgency: (u: 'routine' | 'emergency') => void; showUrgency: boolean; busy: boolean
}) {
  const [gpsErr, setGpsErr] = useState<string | null>(null)
  const [locating, setLocating] = useState(false)
  const gps = () => {
    setGpsErr(null)
    if (!navigator.geolocation) { setGpsErr('Location is not available in this browser. Type a PIN or town below.'); return }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (p) => { setLocating(false); const v = { query: { lat: p.coords.latitude, lon: p.coords.longitude }, label: 'My location (GPS)', precise: true }; onLoc(v); onGo(v) },
      () => { setLocating(false); setGpsErr('Could not get your location. Type a PIN code or town below.') },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }
  const ready = typeof loc.query !== 'string' || loc.query.trim().length > 1
  return (
    <section className="step" aria-labelledby="where-h">
      <h2 id="where-h" className="step-q">Where is the patient?</h2>
      <button className="big-choice gps" onClick={gps} disabled={busy || locating}>
        <span className="big-icon" aria-hidden="true">📍</span>
        <span><strong>{locating ? 'Finding you…' : 'Use my current location'}</strong><span className="muted">Most accurate, if you are with the patient</span></span>
      </button>
      {gpsErr && <div className="note note-warn">{gpsErr}</div>}
      <div className="or"><span>or type a PIN code, town or area</span></div>
      <form onSubmit={(e) => { e.preventDefault(); if (ready) onGo() }} className="where-form">
        <LocationBox value={loc} onChange={onLoc} label={null} showGps={false} autoFocus />
        {showUrgency && (
          <div className="seg" role="radiogroup" aria-label="Urgency">
            {(['routine', 'emergency'] as const).map((u) => (
              <button key={u} type="button" role="radio" aria-checked={urgency === u}
                      className={`seg-btn ${urgency === u ? 'on' : ''} ${u === 'emergency' ? 'seg-emergency' : ''}`} onClick={() => onUrgency(u)}>
                {u === 'emergency' ? 'Emergency' : 'Not urgent'}
              </button>
            ))}
          </div>
        )}
        <button className="btn btn-primary btn-xl" disabled={!ready || busy}>{busy ? 'Finding care…' : 'Find care'}</button>
      </form>
    </section>
  )
}
