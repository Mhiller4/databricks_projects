import { useEffect, useState } from 'react'
import { COMPONENT_LABEL, FIELD_LABEL, T } from '../strings'
import type { Payload, Rec, Weights } from '../types'
import { ConfidenceChip } from './Bits'

function referral(r: Rec, p: Payload): string {
  const svc = (p.query.service as { label: string }).label
  const where = (p.query.location as { display_name: string }).display_name
  return [
    `Referral · ${svc}`,
    `${r.name}${r.facility_type ? ` (${r.facility_type})` : ''} · ${r.distance_km} km from ${where}`,
    `Address: ${r.address ?? 'not listed'} · Phone: ${r.phone ?? 'not listed'}`,
    `Why: ${r.why[0]}`,
    `Confidence: ${r.confidence} (${r.confidence_reason})`,
    `Cautions: ${r.cautions.length ? r.cautions.join('; ') : 'none listed'}`,
    `Source: Care Finder (Virtue Foundation data) · call ahead before travelling`,
  ].join('\n')
}

export function WhyHowDrawer({ rec, payload, weights, onWeights, onClose }: {
  rec: Rec; payload: Payload; weights: Weights; onWeights: (w: Weights) => void; onClose: () => void
}) {
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])
  const b = rec.score_breakdown
  const maxC = Math.max(...Object.values(b.contributions), 0.0001)
  const text = referral(rec, payload)

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={`${T.whyHow}: ${rec.name}`} onClick={(e) => e.stopPropagation()}>
        <header className="drawer-head">
          <div>
            <div className="tier">{rec.tier_label}</div>
            <h2>{rec.name}</h2>
            <div className="muted">{rec.address}</div>
          </div>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close">✕</button>
        </header>

        <section>
          <h4>Why this facility</h4>
          <ul className="plain">{rec.why.map((w) => <li key={w}>{w}</li>)}</ul>
          <div className="row"><ConfidenceChip c={rec.confidence} /><span className="muted small">{rec.confidence_reason}</span></div>
        </section>

        <section>
          <h4>{T.evidence}</h4>
          {rec.citations.map((c, i) => (
            <blockquote key={i} className="quote">
              <span className="quote-field">{FIELD_LABEL[c.field] ?? c.field}</span> “{c.text}”
              {c.third_party && <span className="muted small"> (reads like a listing about another facility)</span>}
            </blockquote>
          ))}
          {rec.source_urls.length > 0 && (
            <div className="sources"><span className="muted small">{T.sources}:</span>
              {rec.source_urls.map((u) => <a key={u} href={u} target="_blank" rel="noreferrer">{u.replace(/^https?:\/\/(www\.)?/, '').slice(0, 48)}</a>)}
            </div>
          )}
        </section>

        {rec.cautions.length > 0 && (
          <section><h4>{T.cautions}</h4><ul className="cautions">{rec.cautions.map((c) => <li key={c}>⚠ {c}</li>)}</ul></section>
        )}

        <section>
          <h4>{T.scoreBreakdown}</h4>
          <div className="bars">
            {Object.entries(b.contributions).map(([k, v]) => (
              <div key={k} className="bar-row">
                <span className="bar-label">{COMPONENT_LABEL[k] ?? k}</span>
                <span className="meter"><span style={{ width: `${(v / maxC) * 100}%` }} /></span>
                <span className="bar-val">{(b.components[k] ?? 0).toFixed(2)} × {(b.weights[k] ?? 0).toFixed(2)}</span>
              </div>
            ))}
          </div>
          <p className="muted small">Score {rec.score.toFixed(3)} · {b.formula} · type fit {b.raw.type_fit} · travel distance τ {b.raw.tau_km} km</p>
        </section>

        <section>
          <h4>{T.weights}</h4>
          {(Object.keys(weights) as (keyof Weights)[]).map((k) => (
            <label key={k} className="slider">
              <span>{COMPONENT_LABEL[k]}</span>
              <input type="range" min={0} max={1} step={0.05} value={weights[k]}
                     onChange={(e) => onWeights({ ...weights, [k]: Number(e.target.value) })} />
              <span className="bar-val">{weights[k].toFixed(2)}</span>
            </label>
          ))}
          <p className="muted small">{T.weightsNote}</p>
        </section>

        {payload.method && (
          <section><h4>{T.gates}</h4><ol className="plain">{payload.method.gates.map((g) => <li key={g}>{g}</li>)}</ol></section>
        )}

        {(payload.skipped_nearby ?? []).length > 0 && (
          <section>
            <h4>{T.whyNotCloser}</h4>
            <ul className="plain">
              {payload.skipped_nearby!.slice(0, 5).map((s) => (
                <li key={s.facility_id}><strong>{s.name}</strong> · {s.distance_km} km: {s.reasons.join('; ')}</li>
              ))}
            </ul>
          </section>
        )}

        <section>
          <h4>{T.referral}</h4>
          <pre className="referral">{text}</pre>
          <button className="btn btn-primary" onClick={() => navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) })}>
            {copied ? `✓ ${T.copied}` : T.copy}
          </button>
        </section>
      </aside>
    </div>
  )
}
