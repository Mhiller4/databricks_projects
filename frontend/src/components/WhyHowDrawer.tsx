import { useEffect, useState } from 'react'
import { COMPONENT_LABEL, FIELD_LABEL, T } from '../strings'
import type { Payload, Rec, Weights } from '../types'
import { buildReferral, ConfidenceChip, directionsUrl, km, telHref, whatsappUrl } from './Bits'
import {
  IconAlert,
  IconCheck,
  IconCopy,
  IconExternal,
  IconNavigation,
  IconPhone,
  IconRefresh,
  IconShare,
  IconX,
} from './Icons'
import { WEIGHT_PRESETS } from './ResultView'

export function WhyHowDrawer({
  rec,
  payload,
  weights,
  defaultWeights,
  onWeights,
  onClose,
  readOnlyWeights = false,
}: {
  rec: Rec
  payload: Payload
  weights: Weights
  defaultWeights?: Weights
  onWeights: (w: Weights) => void
  onClose: () => void
  readOnlyWeights?: boolean
}) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', esc)
    return () => window.removeEventListener('keydown', esc)
  }, [onClose])

  const b = rec.score_breakdown
  const maxC = Math.max(...Object.values(b.contributions), 0.0001)
  const text = buildReferral(rec, payload)
  const weightSum = Object.values(weights).reduce((a, c) => a + c, 0) || 1

  const copy = () => {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    })
  }

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`${T.whyHow}: ${rec.name}`}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="drawer-head">
          <div className="drawer-title-wrap">
            <div className="tier-label">{rec.tier_label ?? 'Verified facility'}</div>
            <h2>{rec.name}</h2>
            <div className="muted small">
              {[rec.facility_type, km(rec.distance_km)].filter(Boolean).join(' · ')}
            </div>
            {rec.address && <div className="muted small mt-1">{rec.address}</div>}
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close panel">
            <IconX size={18} />
          </button>
        </header>

        {/* Primary Quick Actions */}
        <div className="drawer-quick-actions">
          {rec.phone && (
            <a className="btn btn-call btn-sm flex-1" href={telHref(rec.phone)}>
              <IconPhone size={15} />
              <span>Call {rec.phone}</span>
            </a>
          )}
          <a
            className="btn btn-soft btn-sm"
            href={directionsUrl(rec.lat, rec.lon)}
            target="_blank"
            rel="noreferrer"
          >
            <IconNavigation size={15} />
            <span>Directions</span>
          </a>
          {rec.website && (
            <a
              className="btn btn-ghost btn-sm"
              href={rec.website.startsWith('http') ? rec.website : `https://${rec.website}`}
              target="_blank"
              rel="noreferrer"
            >
              <IconExternal size={14} />
              <span>Site</span>
            </a>
          )}
        </div>

        {/* Why this facility */}
        <section className="drawer-sec">
          <h4>Why this facility</h4>
          {rec.tier_reason && <p className="muted small mb-2">{rec.tier_reason}</p>}
          <ul className="plain-list">
            {rec.why.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
          <div className="conf-row-box">
            <ConfidenceChip c={rec.confidence} />
            <span className="muted small">{rec.confidence_reason}</span>
          </div>
        </section>

        {/* Verbatim Evidence & Sources */}
        <section className="drawer-sec">
          <h4>{T.evidence}</h4>
          <div className="quotes-stack">
            {rec.citations.map((c, i) => (
              <blockquote key={i} className="quote">
                <span className="quote-field">{FIELD_LABEL[c.field] ?? c.field}</span> “{c.text}”
                {c.third_party && (
                  <span className="muted small"> (reads like a directory listing referencing another facility)</span>
                )}
              </blockquote>
            ))}
          </div>
          {rec.source_urls.length > 0 && (
            <div className="sources-list">
              <span className="muted small">{T.sources}:</span>
              {rec.source_urls.map((u) => (
                <a key={u} className="source-pill" href={u} target="_blank" rel="noreferrer">
                  <span>{u.replace(/^https?:\/\/(www\.)?/, '').slice(0, 36)}</span>
                  <IconExternal size={11} />
                </a>
              ))}
            </div>
          )}
        </section>

        {/* Cautions */}
        {rec.cautions.length > 0 && (
          <section className="drawer-sec">
            <h4>{T.cautions}</h4>
            <ul className="cautions">
              {rec.cautions.map((c) => (
                <li key={c}>
                  <IconAlert size={14} />
                  <span>{c}</span>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Score breakdown */}
        <section className="drawer-sec">
          <div className="sec-head-row">
            <h4>{T.scoreBreakdown}</h4>
            <span className="score-pill mono">Score {rec.score.toFixed(3)}</span>
          </div>
          <div className="bars">
            {Object.entries(b.contributions).map(([k, v]) => (
              <div key={k} className="bar-row">
                <span className="bar-label">{COMPONENT_LABEL[k] ?? k}</span>
                <span className="meter">
                  <span style={{ width: `${Math.min(100, (v / maxC) * 100)}%` }} />
                </span>
                <span className="bar-val">
                  {(b.components[k] ?? 0).toFixed(2)} × {(b.weights[k] ?? 0).toFixed(2)}
                </span>
              </div>
            ))}
          </div>
          <p className="muted small mt-2">
            {b.formula} · type fit {b.raw.type_fit.toFixed(2)} · travel scale τ {b.raw.tau_km} km
          </p>
        </section>

        {/* Live Weight Sliders */}
        {!readOnlyWeights && (
          <section className="drawer-sec">
            <div className="sec-head-row">
              <h4>{T.weights}</h4>
              {defaultWeights && (
                <button
                  type="button"
                  className="link-subtle small"
                  onClick={() => onWeights(defaultWeights)}
                >
                  <IconRefresh size={13} />
                  <span>Reset</span>
                </button>
              )}
            </div>
            <div className="preset-row mb-3">
              {WEIGHT_PRESETS.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="preset-chip"
                  onClick={() => onWeights(p.weights)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <div className="sliders-stack">
              {(Object.keys(weights) as (keyof Weights)[]).map((k) => {
                const pct = Math.round((weights[k] / weightSum) * 100)
                return (
                  <label key={k} className="slider-row">
                    <span>{COMPONENT_LABEL[k]}</span>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={weights[k]}
                      onChange={(e) => onWeights({ ...weights, [k]: Number(e.target.value) })}
                    />
                    <span className="bar-val mono">{pct}%</span>
                  </label>
                )
              })}
            </div>
            <p className="muted small mt-2">{T.weightsNote}</p>
          </section>
        )}

        {/* Method Gates & Confidence Rules */}
        {payload.method && (
          <section className="drawer-sec">
            <h4>{T.gates}</h4>
            <ol className="plain-list">
              {payload.method.gates.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ol>
          </section>
        )}

        {/* Why not closer */}
        {(payload.skipped_nearby ?? []).length > 0 && (
          <section className="drawer-sec">
            <h4>{T.whyNotCloser}</h4>
            <ul className="skipped-list">
              {payload.skipped_nearby!.slice(0, 5).map((s) => (
                <li key={s.facility_id}>
                  <div className="skipped-head">
                    <strong>{s.name}</strong>
                    <span className="mono muted">{km(s.distance_km)}</span>
                  </div>
                  <div className="small muted">{s.reasons.join('; ')}</div>
                  {s.evidence?.[0]?.text && (
                    <div className="skipped-ev">“{s.evidence[0].text}”</div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Referral note */}
        <section className="drawer-sec">
          <h4>{T.referral}</h4>
          <pre className="referral">{text}</pre>
          <div className="row">
            <button type="button" className="btn btn-primary btn-sm" onClick={copy}>
              {copied ? <IconCheck size={15} /> : <IconCopy size={15} />}
              <span>{copied ? T.copied : T.copy}</span>
            </button>
            <a
              className="btn btn-soft btn-sm"
              href={whatsappUrl(text)}
              target="_blank"
              rel="noreferrer"
            >
              <IconShare size={15} />
              <span>Share via WhatsApp</span>
            </a>
          </div>
        </section>
      </aside>
    </div>
  )
}
