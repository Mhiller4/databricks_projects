import { useEffect, useMemo, useState } from 'react'
import { GROUP_ORDER, SERVICE_INFO, serviceIcon, serviceName } from '../services'
import { COMPONENT_LABEL, FIELD_LABEL, T } from '../strings'
import type { Payload, Rec, Role, Service, Weights } from '../types'
import {
  buildReferral,
  CONFIDENCE_WORDS,
  ConfidenceChip,
  directionsUrl,
  km,
  telHref,
  whatsappUrl,
} from './Bits'
import { CareMap } from './CareMap'
import {
  IconAlert,
  IconCheck,
  IconChevronDown,
  IconCopy,
  IconList,
  IconMap,
  IconMic,
  IconNavigation,
  IconPhone,
  IconPin,
  IconShare,
  IconSliders,
  ServiceIcon,
} from './Icons'
import { LocationBox, type LocValue } from './LocationBox'

export const WEIGHT_PRESETS: { id: string; label: string; weights: Weights }[] = [
  { id: 'balanced', label: 'Balanced', weights: { proximity: 0.35, evidence: 0.3, trust: 0.2, depth: 0.15 } },
  { id: 'closest', label: 'Closest first', weights: { proximity: 0.65, evidence: 0.2, trust: 0.1, depth: 0.05 } },
  { id: 'proof', label: 'Highest proof', weights: { proximity: 0.15, evidence: 0.45, trust: 0.3, depth: 0.1 } },
]

function Quote({ r }: { r: Rec }) {
  const q = r.citations[0]
  if (!q) return null
  return (
    <blockquote className="quote">
      <span className="quote-field">{FIELD_LABEL[q.field] ?? q.field}</span> “{q.text}”
    </blockquote>
  )
}

function FacilityCard({
  r,
  index,
  role,
  payload,
  selected,
  expanded,
  onSelect,
  onToggleExpand,
  onOpenDrawer,
}: {
  r: Rec
  index: number
  role: Role | null
  payload: Payload
  selected: boolean
  expanded: boolean
  onSelect: () => void
  onToggleExpand: () => void
  onOpenDrawer: () => void
}) {
  const [copied, setCopied] = useState(false)
  const isHero = index === 0
  const cautions = (r.call_ahead.length ? r.call_ahead : r.cautions).slice(0, isHero ? 2 : 1)
  const b = r.score_breakdown
  const maxC = Math.max(...Object.values(b.contributions), 0.0001)
  const refText = useMemo(() => buildReferral(r, payload), [r, payload])

  const copyRef = () => {
    navigator.clipboard?.writeText(refText).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1600)
    })
  }

  return (
    <article
      className={`fac-card ${isHero ? 'fac-hero' : ''} ${selected ? 'fac-selected' : ''}`}
      onClick={onSelect}
      aria-label={`${index + 1}. ${r.name}`}
    >
      <div className="fac-top">
        <div className="fac-title-col">
          <div className="fac-tier-row">
            <span className="rank-dot">{index + 1}</span>
            <span className="tier-label">
              {role === 'patient' && isHero
                ? 'Best place to go'
                : role === 'patient'
                  ? 'Backup option'
                  : r.tier_label ?? 'Verified option'}
            </span>
          </div>
          <h3 className={isHero ? 'fac-name-lg' : 'fac-name'}>{r.name}</h3>
          <div className="muted small">
            {[r.facility_type, r.city || r.district, r.state].filter(Boolean).join(' · ')}
          </div>
        </div>
        <div className="fac-right-col">
          <div className={isHero ? 'fac-km-lg' : 'fac-km'}>{km(r.distance_km)}</div>
          <ConfidenceChip c={r.confidence} />
        </div>
      </div>

      <Quote r={r} />

      {cautions.length > 0 && (
        <ul className="cautions">
          {cautions.map((c) => (
            <li key={c}>
              <IconAlert size={14} />
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="fac-actions" onClick={(e) => e.stopPropagation()}>
        {r.phone ? (
          <a className={`btn ${isHero ? 'btn-call' : 'btn-soft'} btn-sm flex-1`} href={telHref(r.phone)}>
            <IconPhone size={15} />
            <span>{isHero ? `Call ${r.phone}` : 'Call'}</span>
          </a>
        ) : (
          <span className="no-phone-tag">No phone listed</span>
        )}
        <a
          className="btn btn-ghost btn-sm"
          href={directionsUrl(r.lat, r.lon)}
          target="_blank"
          rel="noreferrer"
          title="Open directions in Google Maps"
        >
          <IconNavigation size={15} />
          <span className="hide-xs">Directions</span>
        </a>
        <button
          type="button"
          className={`btn btn-ghost btn-sm ${expanded ? 'btn-active-subtle' : ''}`}
          onClick={onToggleExpand}
          aria-expanded={expanded}
        >
          <IconSliders size={14} />
          <span>Proof</span>
        </button>
      </div>

      {/* Inline expandable concise Proof & Referral */}
      {expanded && (
        <div className="inline-proof" onClick={(e) => e.stopPropagation()}>
          <div className="inline-proof-head">
            <strong>Score {r.score.toFixed(2)}</strong>
            <span className="muted small">{CONFIDENCE_WORDS[r.confidence]}</span>
          </div>
          <div className="mini-bars">
            {Object.entries(b.contributions).map(([k, v]) => (
              <div key={k} className="mini-bar-row">
                <span className="muted">{COMPONENT_LABEL[k] ?? k}</span>
                <span className="meter">
                  <span style={{ width: `${Math.min(100, (v / maxC) * 100)}%` }} />
                </span>
                <span className="bar-val">{Math.round((b.weights[k] ?? 0) * 100)}% wt</span>
              </div>
            ))}
          </div>
          <div className="inline-proof-actions">
            <button type="button" className="link-subtle" onClick={copyRef}>
              {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
              <span>{copied ? T.copied : T.copy}</span>
            </button>
            <a
              className="link-subtle"
              href={whatsappUrl(refText)}
              target="_blank"
              rel="noreferrer"
            >
              <IconShare size={14} />
              <span>WhatsApp</span>
            </a>
            <button type="button" className="link-accent ml-auto" onClick={onOpenDrawer}>
              Full evidence &amp; weights →
            </button>
          </div>
        </div>
      )}
    </article>
  )
}

export function ResultView({
  payload,
  role,
  services = [],
  loc,
  onLoc,
  urgency,
  weights,
  busy = false,
  voiceEnabled = false,
  onOpen,
  onClarify,
  onMove,
  onUpdateSearch,
  onWeights,
  onRoleChange,
  onStartVoice,
  onBackHome,
}: {
  payload: Payload
  role: Role | null
  services?: Service[]
  loc?: LocValue
  onLoc?: (v: LocValue) => void
  urgency?: 'routine' | 'emergency'
  weights?: Weights
  busy?: boolean
  voiceEnabled?: boolean
  onOpen: (r: Rec) => void
  onClarify?: (q: string) => void
  onMove?: (p: { lat: number; lon: number }) => void
  onUpdateSearch?: (patch: { service?: string; loc?: LocValue; urgency?: 'routine' | 'emergency' }) => void
  onWeights?: (w: Weights) => void
  onRoleChange?: (r: Role) => void
  onStartVoice?: () => void
  onBackHome?: () => void
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showFunnel, setShowFunnel] = useState(false)
  const [showMoreRanked, setShowMoreRanked] = useState(false)
  const [editing, setEditing] = useState(false)
  const [mobilePane, setMobilePane] = useState<'list' | 'map'>('list')
  const [draftLoc, setDraftLoc] = useState<LocValue>(
    loc ?? { query: '', label: '', precise: null },
  )

  useEffect(() => {
    if (loc) setDraftLoc(loc)
  }, [loc])

  const nearby = payload.recommendations ?? []
  const recs = nearby.length ? nearby : payload.nearest_beyond_radius ?? []
  const visibleRecs = role === 'patient' ? recs.slice(0, 2) : recs

  useEffect(() => {
    if (visibleRecs.length) {
      setSelectedId((prev) =>
        prev && visibleRecs.some((r) => r.facility_id === prev) ? prev : visibleRecs[0].facility_id,
      )
    }
  }, [payload]) // eslint-disable-line react-hooks/exhaustive-deps

  // Clarification state
  if (payload.status === 'needs_clarification') {
    return (
      <section className="narrow-state">
        <div className="state-card">
          <span className="kicker">Location clarification</span>
          <h2>{T.clarifyTitle}</h2>
          <p className="muted">{payload.message}</p>
          <div className="clarify-grid">
            {(payload.options ?? []).map((o) => {
              const q = typeof o === 'string' ? o : o.query
              const label = typeof o === 'string' ? o : o.display_name.replace(' (post office)', '')
              return (
                <button key={q} className="clarify-btn" onClick={() => onClarify?.(q)}>
                  <IconPin size={16} />
                  <strong>{label}</strong>
                </button>
              )
            })}
          </div>
          {onBackHome && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={onBackHome}>
              ← Change search
            </button>
          )}
        </div>
      </section>
    )
  }

  // Error / unknown service / unresolved location state
  if (payload.status !== 'ok') {
    const svcOptions = payload.status === 'unknown_service' ? (payload.options ?? []) : []
    return (
      <section className="narrow-state">
        <div className="state-card">
          <span className="kicker">Search could not complete</span>
          <h2>We couldn’t match that query</h2>
          <div className="notice notice-warn">
            <IconAlert size={16} />
            <span>{payload.message ?? 'Please refine the care type or location.'}</span>
          </div>
          {svcOptions.length > 0 && onUpdateSearch && (
            <div className="chip-cloud">
              {svcOptions.map((opt) => {
                const label = typeof opt === 'string' ? opt : opt.display_name
                const matchKey = services.find((s) => s.label === label)?.key ?? label
                return (
                  <button
                    key={label}
                    type="button"
                    className="example-pill"
                    onClick={() => onUpdateSearch({ service: matchKey })}
                  >
                    {label}
                  </button>
                )
              })}
            </div>
          )}
          {onBackHome && (
            <button type="button" className="btn btn-primary" onClick={onBackHome}>
              ← Edit care or location
            </button>
          )}
        </div>
      </section>
    )
  }

  const q = payload.query as {
    service: { key: string; label: string; tau_km: number }
    location: { display_name: string; ask_for_more_detail?: boolean; more_detail_prompt?: string | null }
    urgency: 'routine' | 'emergency'
    radius_km?: number
  }
  const desert = payload.medical_desert_alert
  const funnel = payload.funnel ?? []
  const totalStart = funnel[0]?.count
  const inRadiusCount = funnel[4]?.count
  const passedCount = funnel[6]?.count
  const shownCount = funnel[7]?.count ?? visibleRecs.length

  const extraRanked = (payload.ranked ?? []).filter(
    (r) => !visibleRecs.some((v) => v.facility_id === r.facility_id),
  )

  const activePreset = !weights
    ? null
    : (WEIGHT_PRESETS.find(
        (p) =>
          Math.abs(p.weights.proximity - weights.proximity) < 0.06 &&
          Math.abs(p.weights.evidence - weights.evidence) < 0.06,
      )?.id ?? null)

  const knownServices = services.length
    ? services
    : Object.entries(SERVICE_INFO).map(([key, v]) => ({
        key,
        label: v.name,
        tau_km: 30,
        synonyms: [],
        note: v.hint,
      }))

  return (
    <section className="results-shell" aria-busy={busy}>
      {/* Compact Inline-Editable Results Query Bar */}
      <div className="results-bar">
        <div className="results-query-summary">
          <div className="results-query-main">
            <span className="query-svc-icon">
              <ServiceIcon name={serviceIcon(q.service.key)} size={18} />
            </span>
            <div>
              <div className="results-title-line">
                <h1>{serviceName(q.service.key, q.service.label)}</h1>
                <span className="muted">near</span>
                {onUpdateSearch ? (
                  <button
                    type="button"
                    className="place-edit-trigger"
                    onClick={() => setEditing((e) => !e)}
                    title="Edit service or location"
                  >
                    {q.location.display_name.replace(' (post office)', '')}
                    <IconChevronDown size={15} className={editing ? 'rot-180' : ''} />
                  </button>
                ) : (
                  <span className="place-static">
                    {q.location.display_name.replace(' (post office)', '')}
                  </span>
                )}
              </div>
              <div className="results-sub-meta">
                <span className={q.urgency === 'emergency' ? 'meta-urgent' : 'muted'}>
                  {q.urgency === 'emergency' ? 'Emergency priority' : 'Routine priority'}
                </span>
                {q.radius_km != null && <span className="muted">· {Math.round(q.radius_km)} km search radius</span>}
                {busy && <span className="updating-pill">Updating…</span>}
              </div>
            </div>
          </div>

          <div className="results-bar-actions">
            {onRoleChange && role && (
              <div className="seg-pill seg-xs hide-sm" role="radiogroup" aria-label="View mode">
                <button
                  type="button"
                  role="radio"
                  aria-checked={role === 'patient'}
                  className={`seg-pill-btn ${role === 'patient' ? 'on' : ''}`}
                  onClick={() => onRoleChange('patient')}
                >
                  Patient
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={role === 'provider'}
                  className={`seg-pill-btn ${role === 'provider' ? 'on' : ''}`}
                  onClick={() => onRoleChange('provider')}
                >
                  Clinician
                </button>
              </div>
            )}
            {onUpdateSearch && (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setEditing((e) => !e)}
              >
                {editing ? 'Close editor' : 'Edit search'}
              </button>
            )}
            {voiceEnabled && onStartVoice && (
              <button type="button" className="btn btn-primary btn-sm" onClick={onStartVoice}>
                <IconMic size={15} />
                <span>Ask follow-up</span>
              </button>
            )}
          </div>
        </div>

        {/* Inline quick-edit panel (zero wizard round-trips) */}
        {editing && onUpdateSearch && (
          <form
            className="inline-editor"
            onSubmit={(e) => {
              e.preventDefault()
              onLoc?.(draftLoc)
              onUpdateSearch({ loc: draftLoc })
              setEditing(false)
            }}
          >
            <div className="editor-field">
              <label className="field-label" htmlFor="edit-svc">
                Care service
              </label>
              <select
                id="edit-svc"
                value={q.service.key}
                onChange={(e) => {
                  onUpdateSearch({ service: e.target.value })
                  setEditing(false)
                }}
              >
                {GROUP_ORDER.map((g) => {
                  const groupItems = knownServices.filter((s) => SERVICE_INFO[s.key]?.group === g)
                  if (!groupItems.length) return null
                  return (
                    <optgroup key={g} label={g}>
                      {groupItems.map((s) => (
                        <option key={s.key} value={s.key}>
                          {serviceName(s.key, s.label)}
                        </option>
                      ))}
                    </optgroup>
                  )
                })}
              </select>
            </div>
            <div className="editor-field editor-loc">
              <LocationBox
                value={draftLoc}
                onChange={setDraftLoc}
                onGpsPick={(v) => {
                  onLoc?.(v)
                  onUpdateSearch({ loc: v })
                  setEditing(false)
                }}
                label="Location"
                compact
                id="edit-loc"
              />
            </div>
            <div className="editor-field editor-urg">
              <span className="field-label">Urgency</span>
              <div className="seg-pill" role="radiogroup" aria-label="Urgency">
                {(['routine', 'emergency'] as const).map((u) => (
                  <button
                    key={u}
                    type="button"
                    role="radio"
                    aria-checked={(urgency ?? q.urgency) === u}
                    className={`seg-pill-btn ${u === 'emergency' ? 'seg-em' : ''} ${(urgency ?? q.urgency) === u ? 'on' : ''}`}
                    onClick={() => onUpdateSearch({ urgency: u })}
                  >
                    {u === 'emergency' ? T.emergency : T.routine}
                  </button>
                ))}
              </div>
            </div>
            <div className="editor-submit">
              <button type="submit" className="btn btn-primary btn-sm" disabled={busy}>
                Update
              </button>
            </div>
          </form>
        )}
      </div>

      {/* Contextual Alerts */}
      {q.location.ask_for_more_detail && q.location.more_detail_prompt && (
        <div className="notice notice-warn">
          <IconAlert size={16} />
          <span>
            {q.location.more_detail_prompt}{' '}
            {onUpdateSearch && (
              <button type="button" className="link-accent" onClick={() => setEditing(true)}>
                Refine area or PIN
              </button>
            )}
          </span>
        </div>
      )}

      {desert?.triggered && desert.message && (
        <div className="banner-desert" role="alert">
          <IconAlert size={18} />
          <div>
            <strong>{T.desertTitle}.</strong> {desert.message}
          </div>
        </div>
      )}

      {/* Compact 1-Line Expandable Funnel Strip */}
      {funnel.length > 0 && (
        <div className="funnel-strip-wrap">
          <button
            type="button"
            className="funnel-strip"
            onClick={() => setShowFunnel((s) => !s)}
            aria-expanded={showFunnel}
          >
            <span className="funnel-summary-text">
              <strong>{totalStart?.toLocaleString('en-IN')}</strong> records
              <span className="funnel-sep">→</span>
              <strong>{inRadiusCount?.toLocaleString('en-IN')}</strong> nearby
              <span className="funnel-sep">→</span>
              <strong>{passedCount?.toLocaleString('en-IN')}</strong> verified
              <span className="funnel-sep">→</span>
              <strong>{shownCount}</strong> {nearby.length ? 'recommended' : 'in range'}
            </span>
            <span className="funnel-strip-right">
              {payload.elapsed_ms != null && (
                <span className="mono muted">{Math.round(payload.elapsed_ms)} ms</span>
              )}
              <span className="funnel-toggle-lbl">
                {showFunnel ? 'Hide gates' : 'How we decided'}
                <IconChevronDown size={14} className={showFunnel ? 'rot-180' : ''} />
              </span>
            </span>
          </button>

          {showFunnel && (
            <div className="funnel-drawer">
              <ol className="funnel-grid">
                {funnel.map((s, i, arr) => (
                  <li key={s.stage} className={i === arr.length - 1 ? 'last' : ''}>
                    <span className="funnel-n">{s.count.toLocaleString('en-IN')}</span>
                    <span className="funnel-s">{s.stage}</span>
                  </li>
                ))}
              </ol>
              {payload.method && (
                <div className="gates-box">
                  <div className="group-h">{T.gates}</div>
                  <ol className="plain-list">
                    {payload.method.gates.map((g) => (
                      <li key={g}>{g}</li>
                    ))}
                  </ol>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Mobile List / Map Switcher */}
      <div className="mobile-pane-toggle">
        <button
          type="button"
          className={`pane-btn ${mobilePane === 'list' ? 'on' : ''}`}
          onClick={() => setMobilePane('list')}
        >
          <IconList size={15} />
          <span>Facilities ({visibleRecs.length})</span>
        </button>
        <button
          type="button"
          className={`pane-btn ${mobilePane === 'map' ? 'on' : ''}`}
          onClick={() => setMobilePane('map')}
        >
          <IconMap size={15} />
          <span>Map view</span>
        </button>
      </div>

      {/* Editorial 50/50 Split Workspace */}
      <div className="results-split">
        {/* Left: Concise Verified Facility Cards */}
        <div className={`results-list-col ${mobilePane === 'map' ? 'hide-mobile' : ''}`}>
          {!nearby.length && visibleRecs.length > 0 && (
            <div className="muted small section-lead">
              Nearest verified options beyond the safe travel distance:
            </div>
          )}

          {visibleRecs.length > 0 ? (
            <div className="cards-stack">
              {visibleRecs.map((r, i) => (
                <FacilityCard
                  key={r.facility_id}
                  r={r}
                  index={i}
                  role={role}
                  payload={payload}
                  selected={selectedId === r.facility_id}
                  expanded={expandedId === r.facility_id}
                  onSelect={() => setSelectedId(r.facility_id)}
                  onToggleExpand={() => {
                    setSelectedId(r.facility_id)
                    setExpandedId((cur) => (cur === r.facility_id ? null : r.facility_id))
                  }}
                  onOpenDrawer={() => onOpen(r)}
                />
              ))}
            </div>
          ) : (
            <div className="notice notice-warn">
              <IconAlert size={16} />
              <span>No verified facility found within 600 km in this dataset.</span>
            </div>
          )}

          {/* Skipped Nearby (Clinician mode) */}
          {role !== 'patient' && (payload.skipped_nearby ?? []).length > 0 && (
            <details className="clinical-panel">
              <summary>
                <span>Closer facilities we skipped ({payload.skipped_nearby!.length})</span>
                <span className="muted small">Why weren’t these shown?</span>
              </summary>
              <ul className="skipped-list">
                {payload.skipped_nearby!.slice(0, 6).map((s) => (
                  <li key={s.facility_id}>
                    <div className="skipped-head">
                      <strong>{s.name}</strong>
                      <span className="mono muted">{km(s.distance_km)}</span>
                    </div>
                    <div className="small muted">{s.reasons.join(' · ')}</div>
                    {s.evidence?.[0]?.text && (
                      <div className="skipped-ev">
                        “{s.evidence[0].text}” ({FIELD_LABEL[s.evidence[0].field] ?? s.evidence[0].field})
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {/* Additional Verified Ranked Facilities (Clinician mode) */}
          {role !== 'patient' && extraRanked.length > 0 && (
            <div className="extra-ranked-wrap">
              <button
                type="button"
                className="link-subtle"
                onClick={() => setShowMoreRanked((s) => !s)}
              >
                <span>
                  {showMoreRanked
                    ? 'Hide additional verified facilities'
                    : `Show ${extraRanked.length} more verified facilities in range`}
                </span>
                <IconChevronDown size={14} className={showMoreRanked ? 'rot-180' : ''} />
              </button>
              {showMoreRanked && (
                <div className="extra-ranked-list">
                  {extraRanked.map((r) => (
                    <div key={r.facility_id} className="extra-row">
                      <div>
                        <strong>{r.name}</strong>
                        <div className="muted small">
                          {km(r.distance_km)} · {r.confidence} confidence · score {r.score.toFixed(2)}
                        </div>
                      </div>
                      <button type="button" className="btn btn-ghost btn-xs" onClick={() => onOpen(r)}>
                        Inspect
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right: Sticky Map + Quick Ranking Priority Controls */}
        <div className={`results-map-col ${mobilePane === 'list' ? 'hide-mobile' : ''}`}>
          <CareMap
            payload={payload}
            selectedId={selectedId}
            onSelect={(r) => setSelectedId(r.facility_id)}
            onPick={(r) => {
              setSelectedId(r.facility_id)
              onOpen(r)
            }}
            onMove={onMove}
            showSkipped={role !== 'patient'}
          />

          {/* Quick Weight Preset Bar */}
          {onWeights && visibleRecs.length > 0 && (
            <div className="weight-bar-card">
              <div className="weight-bar-top">
                <span className="small muted">Ranking priority</span>
                <button
                  type="button"
                  className="link-accent small"
                  onClick={() => {
                    const target = visibleRecs.find((r) => r.facility_id === selectedId) ?? visibleRecs[0]
                    if (target) onOpen(target)
                  }}
                >
                  <IconSliders size={13} />
                  <span>Custom sliders</span>
                </button>
              </div>
              <div className="preset-row">
                {WEIGHT_PRESETS.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    className={`preset-chip ${activePreset === p.id ? 'on' : ''}`}
                    onClick={() => onWeights(p.weights)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
