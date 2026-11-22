import { useMemo, useState, type FormEvent } from 'react'
import { FEATURED_SERVICE_KEYS, GROUP_ORDER, SERVICE_INFO, serviceIcon, serviceName } from '../services'
import { T } from '../strings'
import type { Config, Role, Service } from '../types'
import {
  IconArrowRight,
  IconChevronDown,
  IconMessage,
  IconMic,
  IconPhone,
  IconSearch,
  IconShieldCheck,
  IconStethoscope,
  IconUsers,
  ServiceIcon,
} from './Icons'
import { LocationBox, type LocValue } from './LocationBox'

const QUICK_EXAMPLES: {
  label: string
  sub: string
  service: string
  location: string
  urgency: 'routine' | 'emergency'
  tag?: string
}[] = [
  {
    label: 'Dialysis · Darbhanga, Bihar',
    sub: 'Standard multi-tier verification',
    service: 'dialysis',
    location: 'Darbhanga, Bihar',
    urgency: 'routine',
  },
  {
    label: 'Emergency C-section · Nanded',
    sub: 'Care desert alert + safe radius',
    service: 'emergency_c_section',
    location: 'Nanded, Maharashtra',
    urgency: 'emergency',
    tag: 'Care desert',
  },
  {
    label: 'Cardiac Cath · Bandra, Mumbai',
    sub: 'Urban locality precision check',
    service: 'cardiac_cath',
    location: 'Bandra West, Mumbai Suburban',
    urgency: 'routine',
  },
]

export function TriageCanvas({
  cfg,
  role,
  onRole,
  urgency,
  onUrgency,
  service,
  onService,
  loc,
  onLoc,
  busy,
  onSearch,
  onStartVoice,
  onQuickExample,
  onNavigate,
  webVoice,
}: {
  cfg: Config | null
  role: Role
  onRole: (r: Role) => void
  urgency: 'routine' | 'emergency'
  onUrgency: (u: 'routine' | 'emergency') => void
  service: string
  onService: (k: string) => void
  loc: LocValue
  onLoc: (v: LocValue) => void
  busy: boolean
  onSearch: (override?: { service?: string; loc?: LocValue; urgency?: 'routine' | 'emergency' }) => void
  onStartVoice: (mode: 'voice' | 'text') => void
  onQuickExample: (ex: { service: string; location: string; urgency: 'routine' | 'emergency' }) => void
  onNavigate: (tab: 'methodology' | 'about' | 'policy') => void
  webVoice: boolean
}) {
  const [showAll, setShowAll] = useState(false)
  const [filter, setFilter] = useState('')

  const services: Service[] = useMemo(() => cfg?.services ?? [], [cfg])
  const known = useMemo(() => {
    if (!services.length) return new Set(Object.keys(SERVICE_INFO))
    return new Set(services.map((s) => s.key))
  }, [services])

  const featuredKeys = useMemo(() => {
    const list = FEATURED_SERVICE_KEYS.filter((k) => known.has(k))
    if (service && !list.includes(service) && SERVICE_INFO[service]) {
      return [service, ...list.slice(0, 5)]
    }
    return list
  }, [known, service])

  const f = filter.trim().toLowerCase()
  const match = (key: string) => {
    if (!f) return true
    const s = services.find((x) => x.key === key)
    const i = SERVICE_INFO[key]
    return [i?.name, i?.hint, s?.label, ...(s?.synonyms ?? [])].some((t) => t?.toLowerCase().includes(f))
  }

  const ready = Boolean(service) && (typeof loc.query !== 'string' || loc.query.trim().length > 1)

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (ready && !busy) onSearch()
  }

  const rawRecords = cfg?.funnel_base?.raw_records
    ? cfg.funnel_base.raw_records.toLocaleString('en-IN')
    : '10,088'

  return (
    <div className="canvas-wrap">
      {/* Focused Direction B Triage Surface */}
      <section className="triage-hero" aria-labelledby="hero-title">
        <div className="triage-meta-row">
          <div className="seg-pill" role="radiogroup" aria-label="Who is searching">
            <button
              type="button"
              role="radio"
              aria-checked={role === 'patient'}
              className={`seg-pill-btn ${role === 'patient' ? 'on' : ''}`}
              onClick={() => onRole('patient')}
            >
              <IconUsers size={15} />
              <span>{T.rolePatient}</span>
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={role === 'provider'}
              className={`seg-pill-btn ${role === 'provider' ? 'on' : ''}`}
              onClick={() => onRole('provider')}
            >
              <IconStethoscope size={15} />
              <span>{T.roleProvider}</span>
            </button>
          </div>

          <div className="seg-pill seg-urgency" role="radiogroup" aria-label="Urgency">
            <button
              type="button"
              role="radio"
              aria-checked={urgency === 'routine'}
              className={`seg-pill-btn ${urgency === 'routine' ? 'on' : ''}`}
              onClick={() => onUrgency('routine')}
            >
              {T.routine}
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={urgency === 'emergency'}
              className={`seg-pill-btn seg-em ${urgency === 'emergency' ? 'on' : ''}`}
              onClick={() => onUrgency('emergency')}
            >
              {T.emergency}
            </button>
          </div>
        </div>

        <div className="hero-heading">
          <h1 id="hero-title">Find care nearby</h1>
          <p className="muted">
            {role === 'provider'
              ? 'For referrals across India. Each result quotes the facility’s own record and shows how it was scored.'
              : 'Tell us what care is needed and where. We show what each place’s record says and how sure we are.'}
          </p>
        </div>

        {/* Phone line first: calling works on any phone. Browser voice only when no number is set. */}
        {cfg?.phone_number ? (
          <a className="voice-hero-bar voice-hero-main" href={`tel:${cfg.phone_number.replace(/[^\d+]/g, '')}`}>
            <span className="voice-orb-mini">
              <IconPhone size={19} />
            </span>
            <span className="voice-hero-copy">
              <strong>Call {cfg.phone_number}</strong>
              <span className="muted small">
                Talk to care.in in English, Hindi or another Indian language. Try “My mother needs dialysis
                near Bandra, Mumbai.”
              </span>
            </span>
            <span className="btn btn-soft btn-sm">Call</span>
          </a>
        ) : (
          webVoice && (
            <div className="voice-hero-bar">
              <button type="button" className="voice-hero-main" onClick={() => onStartVoice('voice')}>
                <span className="voice-orb-mini">
                  <IconMic size={19} />
                </span>
                <span className="voice-hero-copy">
                  <strong>Speak in English, Hindi or another Indian language</strong>
                  <span className="muted small">Try “My mother needs dialysis near Bandra, Mumbai.”</span>
                </span>
                <span className="btn btn-soft btn-sm">Talk</span>
              </button>
              <button
                type="button"
                className="voice-chat-trigger"
                onClick={() => onStartVoice('text')}
                title="Type to the assistant"
                aria-label="Open text assistant"
              >
                <IconMessage size={17} />
                <span className="hide-sm">Chat</span>
              </button>
            </div>
          )
        )}

        {/* Compressed 2-Part Search Card */}
        <form className="triage-card" onSubmit={handleSubmit}>
          {/* 1 · Care needed */}
          <div className="triage-block">
            <div className="triage-block-head">
              <span className="step-num">1</span>
              <span className="field-label inline">{T.service}</span>
              {service && (
                <span className="selected-svc-pill">
                  <ServiceIcon name={serviceIcon(service)} size={13} />
                  {serviceName(service)}
                </span>
              )}
              <button
                type="button"
                className="link-subtle ml-auto"
                onClick={() => setShowAll((s) => !s)}
                aria-expanded={showAll}
              >
                <span>{showAll ? 'Show fewer' : 'All 16 services'}</span>
                <IconChevronDown size={14} className={showAll ? 'rot-180' : ''} />
              </button>
            </div>

            {!showAll ? (
              <div className="svc-chip-grid">
                {featuredKeys.map((k) => {
                  const info = SERVICE_INFO[k]
                  const active = service === k
                  return (
                    <button
                      key={k}
                      type="button"
                      className={`svc-chip ${active ? 'on' : ''}`}
                      onClick={() => onService(k)}
                      aria-pressed={active}
                    >
                      <span className="svc-chip-ico">
                        <ServiceIcon name={info.icon} size={17} />
                      </span>
                      <span className="svc-chip-txt">
                        <strong>{info.name}</strong>
                        <span>{info.hint}</span>
                      </span>
                    </button>
                  )
                })}
              </div>
            ) : (
              <div className="all-services-box">
                <div className="combo">
                  <span className="input-icon">
                    <IconSearch size={15} />
                  </span>
                  <input
                    className="has-icon-left input-sm"
                    placeholder="Filter, e.g. kidney, NICU, cataract, trauma, scan"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    aria-label="Filter medical services"
                  />
                </div>
                <div className="all-svc-groups">
                  {GROUP_ORDER.map((g) => {
                    const keys = Object.entries(SERVICE_INFO)
                      .filter(([k, v]) => v.group === g && known.has(k) && match(k))
                      .map(([k]) => k)
                    if (!keys.length) return null
                    return (
                      <div key={g} className="all-svc-group">
                        <div className="group-h">{g}</div>
                        <div className="svc-chip-grid">
                          {keys.map((k) => {
                            const info = SERVICE_INFO[k]
                            const active = service === k
                            return (
                              <button
                                key={k}
                                type="button"
                                className={`svc-chip ${active ? 'on' : ''}`}
                                onClick={() => {
                                  onService(k)
                                  setShowAll(false)
                                  setFilter('')
                                }}
                                aria-pressed={active}
                              >
                                <span className="svc-chip-ico">
                                  <ServiceIcon name={info.icon} size={17} />
                                </span>
                                <span className="svc-chip-txt">
                                  <strong>{info.name}</strong>
                                  <span>{info.hint}</span>
                                </span>
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          <div className="triage-divider" />

          {/* 2 · Patient location */}
          <div className="triage-block">
            <div className="triage-block-head">
              <span className="step-num">2</span>
              <span className="field-label inline">{T.location}</span>
            </div>
            <LocationBox
              value={loc}
              onChange={onLoc}
              onGpsPick={(v) => {
                if (service) onSearch({ loc: v })
              }}
              label={null}
              showGps
              id="triage-loc"
            />
          </div>

          <div className="triage-submit-row">
            <button
              type="submit"
              className={`btn btn-primary btn-lg w-full ${urgency === 'emergency' ? 'btn-urgent-go' : ''}`}
              disabled={!ready || busy}
            >
              <span>{busy ? T.searching : urgency === 'emergency' ? 'Find urgent care now' : T.search}</span>
              {!busy && <IconArrowRight size={17} />}
            </button>
          </div>
        </form>

        {/* Quick 1-click scenarios for fast testing & demos */}
        <div className="quick-examples">
          <span className="muted small">Try an example:</span>
          <div className="quick-example-list">
            {QUICK_EXAMPLES.map((ex) => (
              <button
                key={ex.label}
                type="button"
                className="example-pill"
                disabled={busy}
                onClick={() => onQuickExample(ex)}
              >
                <span>{ex.label}</span>
                {ex.tag && <span className="example-tag">{ex.tag}</span>}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Clinical Trust & Governance Strip */}
      <section className="trust-strip" aria-label="Platform verification standards">
        <div className="trust-metrics">
          <div className="trust-stat">
            <strong>{rawRecords}</strong>
            <span>Facility records across India</span>
          </div>
          <div className="trust-stat">
            <strong>16</strong>
            <span>Services you can search for</span>
          </div>
          <div className="trust-stat">
            <strong>165k+</strong>
            <span>PIN codes and places</span>
          </div>
          <div className="trust-stat">
            <strong>5 checks</strong>
            <span>Every result has to pass them</span>
          </div>
        </div>

        <div className="trust-foot-row">
          <span className="trust-badge-line">
            <IconShieldCheck size={15} />
            <span>Every facility, distance and quote comes from the dataset, not from an AI model.</span>
          </span>
          <div className="trust-links">
            <button type="button" className="link-subtle" onClick={() => onNavigate('methodology')}>
              How scoring works
            </button>
            <button type="button" className="link-subtle" onClick={() => onNavigate('about')}>
              Where the data comes from
            </button>
            <button type="button" className="link-subtle" onClick={() => onNavigate('policy')}>
              Clinical policy
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
