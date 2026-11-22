import { useCallback, useEffect, useRef, useState } from 'react'
import { getConfig, recommend, type SearchArgs } from './api'
import { IconMoon, IconPhone, IconPlus, IconSun } from './components/Icons'
import { InfoPages, type InfoTab } from './components/InfoPages'
import type { LocValue } from './components/LocationBox'
import { ResultView } from './components/ResultView'
import { TriageCanvas } from './components/TriageCanvas'
import { VoiceSheet, type VoiceTrigger } from './components/VoiceSheet'
import { WhyHowDrawer } from './components/WhyHowDrawer'
import { T } from './strings'
import type { Config, Payload, Rec, Role, Weights } from './types'

type NavTab = 'find' | InfoTab

const DEFAULT_WEIGHTS: Record<'routine' | 'emergency', Weights> = {
  routine: { proximity: 0.35, evidence: 0.3, trust: 0.2, depth: 0.15 },
  emergency: { proximity: 0.5, evidence: 0.25, trust: 0.15, depth: 0.1 },
}
const EMPTY_LOC: LocValue = { query: '', label: '', precise: null }

function useTheme() {
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    const saved = typeof window !== 'undefined' ? localStorage.getItem('cf-theme') : null
    if (saved === 'light' || saved === 'dark') return saved
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches
      ? 'dark'
      : 'light'
  })

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('cf-theme', theme)
  }, [theme])

  return [theme, () => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))] as const
}

export default function App() {
  const [theme, toggleTheme] = useTheme()
  const [cfg, setCfg] = useState<Config | null>(null)
  const [tab, setTab] = useState<NavTab>('find')
  const [role, setRole] = useState<Role>('patient')
  const [urgency, setUrgency] = useState<'routine' | 'emergency'>('routine')
  const [service, setService] = useState('dialysis')
  const [loc, setLoc] = useState<LocValue>(EMPTY_LOC)
  const [payload, setPayload] = useState<Payload | null>(null)
  const [busy, setBusy] = useState(false)
  const [drawer, setDrawer] = useState<Rec | null>(null)
  const [weights, setWeights] = useState<Weights>(DEFAULT_WEIGHTS.routine)
  const [voiceTrigger, setVoiceTrigger] = useState<VoiceTrigger | null>(null)
  const last = useRef<SearchArgs | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    getConfig()
      .then(setCfg)
      .catch(() => setCfg({ phone_number: '', services: [], funnel_base: {}, livekit_enabled: false }))
  }, [])

  const run = useCallback(
    async (args: SearchArgs) => {
      last.current = args
      setBusy(true)
      setTab('find')
      try {
        const p = await recommend(args)
        setPayload(p)
        setDrawer((d) => {
          if (!d || p.status !== 'ok') return null
          const pool = [
            ...(p.recommendations ?? []),
            ...(p.nearest_beyond_radius ?? []),
            ...(p.ranked ?? []),
          ]
          return pool.find((r) => r.facility_id === d.facility_id) ?? d
        })
      } catch (e) {
        setPayload({
          status: 'error',
          message: `Search failed: ${(e as Error).message}`,
          query: { service: args.service, location: null, urgency: args.urgency },
        })
      } finally {
        setBusy(false)
      }
    },
    [],
  )

  const handleSearch = (override?: {
    service?: string
    loc?: LocValue
    urgency?: 'routine' | 'emergency'
  }) => {
    const svc = override?.service ?? service
    const l = override?.loc ?? loc
    const u = override?.urgency ?? urgency
    if (override?.service !== undefined) setService(svc)
    if (override?.loc !== undefined) setLoc(l)
    if (override?.urgency !== undefined) setUrgency(u)
    const w = DEFAULT_WEIGHTS[u]
    setWeights(w)
    run({ service: svc, location: l.query, urgency: u, weights: w, audience: role })
  }

  const handleQuickExample = (ex: {
    service: string
    location: string
    urgency: 'routine' | 'emergency'
  }) => {
    const nextLoc: LocValue = { query: ex.location, label: ex.location, precise: null }
    handleSearch({ service: ex.service, loc: nextLoc, urgency: ex.urgency })
  }

  const onVoiceResult = useCallback(
    (p: Payload) => {
      setPayload(p)
      setTab('find')
      if (p.status === 'ok') {
        const q = p.query as {
          service: { key: string }
          location: { lat: number; lon: number; display_name: string; is_precise?: boolean }
          urgency: 'routine' | 'emergency'
          weights?: Weights
        }
        setService(q.service.key)
        setUrgency(q.urgency)
        setLoc({
          query: { lat: q.location.lat, lon: q.location.lon },
          label: q.location.display_name.replace(' (post office)', ''),
          precise: q.location.is_precise ?? null,
        })
        if (q.weights) setWeights(q.weights)
        last.current = {
          service: q.service.key,
          location: { lat: q.location.lat, lon: q.location.lon },
          urgency: q.urgency,
          weights: q.weights ?? null,
          audience: role,
        }
      }
    },
    [role],
  )

  const onWeights = (w: Weights) => {
    setWeights(w)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => {
      if (last.current) run({ ...last.current, weights: w })
    }, 150)
  }

  const onMove = (p: { lat: number; lon: number }) => {
    if (!last.current) return
    setLoc({ query: p, label: `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`, precise: true })
    run({ ...last.current, location: p })
  }

  const onClarify = (q: string) => {
    setLoc({ query: q, label: q, precise: null })
    if (last.current) run({ ...last.current, location: q })
  }

  const resetToHome = () => {
    setTab('find')
    setPayload(null)
    setDrawer(null)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const triggerVoice = (mode: 'voice' | 'text') => {
    setVoiceTrigger((v) => ({ mode, seq: (v?.seq ?? 0) + 1 }))
  }

  const showResults = tab === 'find' && payload !== null
  // Browser voice keeps dropping in testing; when a phone line is set, the page offers that instead.
  const webVoice = !!cfg?.livekit_enabled && !cfg?.phone_number

  return (
    <div className="app">
      {/* Top bar: 108 SOS stays pinned top right */}
      <header className="topbar">
        <div className="topbar-inner">
          <button type="button" className="brand" onClick={resetToHome} aria-label="care.in home">
            <span className="logo">
              <IconPlus size={18} />
            </span>
            <span className="brand-text">
              <strong>{T.appName}</strong>
              <span className="brand-sub hide-xs">Hospitals and clinics in India</span>
            </span>
          </button>

          <nav className="topnav" aria-label="Primary navigation">
            {(
              [
                ['find', 'Find care'],
                ['methodology', 'How it works'],
                ['about', 'About'],
                ['policy', 'Policy'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                className={`nav-link ${tab === key ? 'on' : ''}`}
                onClick={() => {
                  setTab(key)
                  window.scrollTo({ top: 0, behavior: 'smooth' })
                }}
              >
                {label}
              </button>
            ))}
          </nav>

          <div className="bar-right">
            {cfg?.phone_number && (
              <a
                className="helpline-pill hide-sm"
                href={`tel:${cfg.phone_number.replace(/\s/g, '')}`}
              >
                <IconPhone size={14} />
                <span>{cfg.phone_number}</span>
              </a>
            )}
            <button
              type="button"
              className="icon-btn theme-btn"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
              title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            >
              {theme === 'dark' ? <IconSun size={17} /> : <IconMoon size={17} />}
            </button>
            <a className="sos-pill" href="tel:108" aria-label="Call 108 emergency ambulance">
              108 SOS
            </a>
          </div>
        </div>
      </header>

      <main className={`main ${showResults ? 'main-wide' : tab !== 'find' ? 'main-prose' : 'main-canvas'}`}>
        {tab === 'find' && !payload && (
          <TriageCanvas
            cfg={cfg}
            role={role}
            onRole={setRole}
            urgency={urgency}
            onUrgency={setUrgency}
            service={service}
            onService={setService}
            loc={loc}
            onLoc={setLoc}
            busy={busy}
            onSearch={handleSearch}
            onStartVoice={triggerVoice}
            onQuickExample={handleQuickExample}
            onNavigate={(t) => {
              setTab(t)
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
            webVoice={webVoice}
          />
        )}

        {showResults && payload && (
          <ResultView
            payload={payload}
            role={role}
            services={cfg?.services ?? []}
            loc={loc}
            onLoc={setLoc}
            urgency={urgency}
            weights={weights}
            busy={busy}
            voiceEnabled={webVoice}
            onOpen={setDrawer}
            onClarify={onClarify}
            onMove={onMove}
            onUpdateSearch={handleSearch}
            onWeights={onWeights}
            onRoleChange={setRole}
            onStartVoice={() => triggerVoice('voice')}
            onBackHome={resetToHome}
          />
        )}

        {tab !== 'find' && (
          <InfoPages
            tab={tab}
            cfg={cfg}
            onStartSearch={() => {
              setTab('find')
              window.scrollTo({ top: 0, behavior: 'smooth' })
            }}
          />
        )}
      </main>

      <footer className="site-footer">
        <div className="footer-inner">
          <div className="footer-left">
            <span className="footer-brand">
              <span className="logo logo-sm">
                <IconPlus size={13} />
              </span>
              <strong>{T.appName}</strong>
            </span>
            <span className="muted small">{T.footer}</span>
          </div>
          <div className="footer-links">
            <button type="button" className="link-subtle small" onClick={() => setTab('methodology')}>
              How it works
            </button>
            <button type="button" className="link-subtle small" onClick={() => setTab('about')}>
              About
            </button>
            <button type="button" className="link-subtle small" onClick={() => setTab('policy')}>
              Policy
            </button>
            <a className="link-subtle small" href="/monitor">
              Live call monitor
            </a>
          </div>
        </div>
      </footer>

      <VoiceSheet
        enabled={webVoice}
        role={role}
        onResult={onVoiceResult}
        trigger={voiceTrigger}
        showFab={showResults}
      />

      {drawer && payload?.status === 'ok' && (
        <WhyHowDrawer
          rec={drawer}
          payload={payload}
          weights={weights}
          defaultWeights={DEFAULT_WEIGHTS[urgency]}
          onWeights={onWeights}
          onClose={() => setDrawer(null)}
        />
      )}
    </div>
  )
}
