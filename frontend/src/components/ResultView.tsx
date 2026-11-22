import { useState } from 'react'
import { serviceName } from '../services'
import { FIELD_LABEL } from '../strings'
import type { Payload, Rec, Role } from '../types'
import { CONFIDENCE_WORDS, ConfidenceChip, directionsUrl, km, telHref } from './Bits'
import { CareMap } from './CareMap'

function Quote({ r }: { r: Rec }) {
  const q = r.citations[0]
  if (!q) return null
  return (
    <blockquote className="quote">
      <span className="quote-field">{FIELD_LABEL[q.field] ?? q.field}</span> “{q.text}”
    </blockquote>
  )
}

function Hero({ r, role, onOpen }: { r: Rec; role: Role | null; onOpen: () => void }) {
  const cautions = (r.call_ahead.length ? r.call_ahead : r.cautions).slice(0, 2)
  return (
    <article className="hero" aria-label={`Best option: ${r.name}`}>
      <div className="hero-tier">{role === 'patient' ? 'Best place to go' : r.tier_label ?? 'Best option'}</div>
      <h2 className="hero-name">{r.name}</h2>
      <div className="muted">{[r.facility_type, r.city || r.district, r.state].filter(Boolean).join(' · ')}</div>
      <div className="hero-facts">
        <span className="hero-km">{km(r.distance_km)}</span>
        <span className="hero-conf"><ConfidenceChip c={r.confidence} /> <span>{CONFIDENCE_WORDS[r.confidence]}</span></span>
      </div>
      <Quote r={r} />
      {cautions.length > 0 && <ul className="cautions">{cautions.map((c) => <li key={c}>⚠ {c}</li>)}</ul>}
      <div className="hero-actions">
        {r.phone
          ? <a className="btn btn-call" href={telHref(r.phone)}>📞 Call {r.phone}</a>
          : <span className="note note-warn">No phone number listed: check the address before travelling.</span>}
        <a className="btn btn-ghost" href={directionsUrl(r.lat, r.lon)} target="_blank" rel="noreferrer">🧭 Directions</a>
        <button className="btn btn-ghost" onClick={onOpen}>Why this one? ▸</button>
      </div>
    </article>
  )
}

function OptionRow({ r, onOpen }: { r: Rec; onOpen: () => void }) {
  return (
    <article className="option">
      <div className="option-main">
        <div className="tier">{r.tier_label}</div>
        <strong>{r.name}</strong>
        <div className="muted small">{km(r.distance_km)} · {r.confidence} confidence{r.facility_type ? ` · ${r.facility_type}` : ''}</div>
        <Quote r={r} />
      </div>
      <div className="option-actions">
        {r.phone && <a className="btn btn-primary" href={telHref(r.phone)} aria-label={`Call ${r.name}`}>📞</a>}
        <button className="btn btn-ghost" onClick={onOpen}>Why? ▸</button>
      </div>
    </article>
  )
}

export function ResultView({ payload, role, onOpen, onClarify, onEditPlace, onEditCare, onMove }: {
  payload: Payload; role: Role | null; onOpen: (r: Rec) => void; onClarify?: (q: string) => void
  onEditPlace?: () => void; onEditCare?: () => void; onMove?: (p: { lat: number; lon: number }) => void
}) {
  const [showMap, setShowMap] = useState(() => window.matchMedia?.('(min-width: 900px)').matches ?? false)

  if (payload.status === 'needs_clarification') {
    return (
      <section className="step">
        <h2 className="step-q">Which one did you mean?</h2>
        <p className="muted">{payload.message}</p>
        <div className="big-choices">
          {(payload.options ?? []).map((o) => {
            const q = typeof o === 'string' ? o : o.query
            const label = typeof o === 'string' ? o : o.display_name.replace(' (post office)', '')
            return <button key={q} className="big-choice" onClick={() => onClarify?.(q)}><strong>{label}</strong></button>
          })}
        </div>
      </section>
    )
  }
  if (payload.status !== 'ok') {
    return (
      <section className="step">
        <h2 className="step-q">We couldn't search that</h2>
        <div className="note note-warn">{payload.message ?? 'Something went wrong.'}</div>
        <div className="row">
          {onEditPlace && <button className="btn btn-primary" onClick={onEditPlace}>Change the place</button>}
          {onEditCare && <button className="btn btn-ghost" onClick={onEditCare}>Change the care</button>}
        </div>
      </section>
    )
  }

  const q = payload.query as { service: { key: string; label: string }; location: { display_name: string; ask_for_more_detail?: boolean; more_detail_prompt?: string | null } }
  const nearby = payload.recommendations ?? []
  const recs = nearby.length ? nearby : payload.nearest_beyond_radius ?? []
  const desert = payload.medical_desert_alert
  const [top, ...rest] = recs
  const others = role === 'patient' ? rest.slice(0, 1) : rest

  return (
    <section className="result-view">
      <div className="result-head">
        <div>
          <div className="muted small">Results for</div>
          <h2>{serviceName(q.service.key, q.service.label)} near {q.location.display_name.replace(' (post office)', '')}</h2>
        </div>
        <div className="row">
          {onEditCare && <button className="link" onClick={onEditCare}>Change care</button>}
          {onEditPlace && <button className="link" onClick={onEditPlace}>Change place</button>}
        </div>
      </div>

      {q.location.ask_for_more_detail && q.location.more_detail_prompt && (
        <div className="note note-warn">⚠ {q.location.more_detail_prompt} {onEditPlace && <button className="link" onClick={onEditPlace}>Add an area</button>}</div>
      )}
      {desert?.triggered && desert.message && <div className="banner banner-red" role="alert"><strong>No verified facility nearby.</strong> {desert.message}</div>}
      {!nearby.length && recs.length > 0 && <div className="muted small">Nearest options we can verify, beyond the safe travel distance:</div>}

      {top ? <Hero r={top} role={role} onOpen={() => onOpen(top)} /> : <div className="note note-warn">No verified facility found within 600 km in this dataset.</div>}

      {others.length > 0 && (
        <div className="options">
          <h3 className="group-h">{role === 'patient' ? 'If you can’t reach them' : 'Other options'}</h3>
          {others.map((r) => <OptionRow key={r.facility_id} r={r} onOpen={() => onOpen(r)} />)}
        </div>
      )}

      {role !== 'patient' && (payload.skipped_nearby ?? []).length > 0 && (
        <details className="panel">
          <summary>Closer facilities we skipped ({payload.skipped_nearby!.length})</summary>
          <ul className="plain">
            {payload.skipped_nearby!.slice(0, 5).map((s) => <li key={s.facility_id}><strong>{s.name}</strong> · {km(s.distance_km)}: {s.reasons[0]}</li>)}
          </ul>
        </details>
      )}

      <details className="panel" open={showMap} onToggle={(e) => setShowMap((e.target as HTMLDetailsElement).open)}>
        <summary>Map</summary>
        {showMap && <CareMap payload={payload} onMove={onMove} onPick={onOpen} />}
      </details>

      <details className="panel">
        <summary>How we decided{payload.elapsed_ms != null ? ` · ${Math.round(payload.elapsed_ms)} ms` : ''}</summary>
        <ol className="funnel-steps">
          {(payload.funnel ?? []).map((s, i, a) => (
            <li key={s.stage} className={i === a.length - 1 ? 'last' : ''}>
              <span className="funnel-n">{s.count.toLocaleString('en-IN')}</span><span className="funnel-s">{s.stage}</span>
            </li>
          ))}
        </ol>
        {payload.method && <><h4>Every recommendation must pass</h4><ol className="plain">{payload.method.gates.map((g) => <li key={g}>{g}</li>)}</ol></>}
      </details>
    </section>
  )
}
