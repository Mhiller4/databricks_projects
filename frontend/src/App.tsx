import { useCallback, useEffect, useRef, useState } from 'react'
import { getConfig, recommend, type SearchArgs } from './api'
import type { LocValue } from './components/LocationBox'
import { ResultView } from './components/ResultView'
import { CareStep, EmergencyStep, WhereStep, WhoStep } from './components/Steps'
import { VoiceSheet } from './components/VoiceSheet'
import { WhyHowDrawer } from './components/WhyHowDrawer'
import { serviceName } from './services'
import { T } from './strings'
import type { Config, Payload, Rec, Role, Weights } from './types'

type Step = 'who' | 'emergency' | 'care' | 'where' | 'result'
const DEFAULT_WEIGHTS: Record<'routine' | 'emergency', Weights> = {
  routine: { proximity: 0.35, evidence: 0.3, trust: 0.2, depth: 0.15 },
  emergency: { proximity: 0.5, evidence: 0.25, trust: 0.15, depth: 0.1 },
}
const EMPTY_LOC: LocValue = { query: '', label: '', precise: null }

export default function App() {
  const [cfg, setCfg] = useState<Config | null>(null)
  const [step, setStep] = useState<Step>('who')
  const [role, setRole] = useState<Role | null>(null)
  const [urgency, setUrgency] = useState<'routine' | 'emergency'>('routine')
  const [service, setService] = useState('')
  const [loc, setLoc] = useState<LocValue>(EMPTY_LOC)
  const [payload, setPayload] = useState<Payload | null>(null)
  const [busy, setBusy] = useState(false)
  const [drawer, setDrawer] = useState<Rec | null>(null)
  const [weights, setWeights] = useState<Weights>(DEFAULT_WEIGHTS.routine)
  const last = useRef<SearchArgs | null>(null)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => { getConfig().then(setCfg).catch(() => setCfg({ phone_number: '', services: [], funnel_base: {}, livekit_enabled: false })) }, [])
  useEffect(() => { window.scrollTo({ top: 0, behavior: 'smooth' }) }, [step])

  const run = useCallback(async (args: SearchArgs) => {
    last.current = args
    setBusy(true)
    try {
      const p = await recommend(args)
      setPayload(p)
      setStep('result')
      setDrawer((d) => (d && p.status === 'ok' ? [...(p.recommendations ?? []), ...(p.nearest_beyond_radius ?? [])].find((r) => r.facility_id === d.facility_id) ?? null : null))
    } catch (e) {
      setPayload({ status: 'error', message: `Search failed: ${(e as Error).message}`, query: { service, location: null, urgency: args.urgency } })
      setStep('result')
    } finally { setBusy(false) }
  }, [service])

  const go = (override?: LocValue) => {
    const w = DEFAULT_WEIGHTS[urgency]
    setWeights(w)
    run({ service, location: (override ?? loc).query, urgency, weights: w, audience: role })
  }

  const onVoiceResult = useCallback((p: Payload) => {
    setPayload(p)
    setStep('result')
    if (p.status === 'ok') {
      const q = p.query as { service: { key: string }; location: { lat: number; lon: number; display_name: string; is_precise?: boolean }; urgency: 'routine' | 'emergency'; weights?: Weights }
      setService(q.service.key)
      setUrgency(q.urgency)
      setLoc({ query: { lat: q.location.lat, lon: q.location.lon }, label: q.location.display_name, precise: q.location.is_precise ?? null })
      if (q.weights) setWeights(q.weights)
      last.current = { service: q.service.key, location: { lat: q.location.lat, lon: q.location.lon }, urgency: q.urgency, weights: q.weights ?? null, audience: role }
    }
  }, [role])

  const onWeights = (w: Weights) => {
    setWeights(w)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => last.current && run({ ...last.current, weights: w }), 150)
  }
  const onMove = (p: { lat: number; lon: number }) => {
    if (!last.current) return
    setLoc({ query: p, label: `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`, precise: true })
    run({ ...last.current, location: p })
  }
  const onClarify = (q: string) => { setLoc({ query: q, label: q, precise: null }); if (last.current) run({ ...last.current, location: q }) }
  const restart = () => { setStep('who'); setRole(null); setService(''); setLoc(EMPTY_LOC); setPayload(null); setUrgency('routine'); setDrawer(null) }

  const order: Step[] = role === 'patient' ? ['who', 'emergency', 'care', 'where'] : ['who', 'care', 'where']
  const idx = order.indexOf(step)
  const back = () => { if (step === 'result') setStep('where'); else if (idx > 0) setStep(order[idx - 1]) }

  return (
    <div className={`app step-${step}`}>
      <header className="bar">
        <button className="brand" onClick={restart} aria-label="Start over">
          <span className="logo" aria-hidden="true">+</span><span><strong>{T.appName}</strong><span className="muted small">Find the right care in India</span></span>
        </button>
        <div className="bar-right">
          {cfg?.phone_number && <a className="phone" href={`tel:${cfg.phone_number.replace(/\s/g, '')}`}>📞 <span className="hide-sm">Call </span>{cfg.phone_number}</a>}
          <a className="sos" href="tel:108" aria-label="Call 108 ambulance">108</a>
        </div>
      </header>

      {step !== 'who' && (
        <nav className="crumbs" aria-label="Progress">
          <button className="link" onClick={back}>← Back</button>
          {step !== 'result' && <span className="muted small">Step {idx + 1} of {order.length}</span>}
          <span className="crumb-chips">
            {role && <span className="crumb">{role === 'patient' ? 'Patient / family' : 'Health worker'}</span>}
            {urgency === 'emergency' && <span className="crumb crumb-red">Emergency</span>}
            {service && step !== 'care' && <button className="crumb" onClick={() => setStep('care')}>{serviceName(service)}</button>}
          </span>
        </nav>
      )}

      <main className={step === 'result' ? 'main wide' : 'main'}>
        {step === 'who' && (
          <>
            <p className="intro">Tell us what care is needed and where. We’ll show the best place to go, why we chose it, and how sure we are.</p>
            <WhoStep onPick={(r) => { setRole(r); setStep(r === 'patient' ? 'emergency' : 'care') }} />
          </>
        )}
        {step === 'emergency' && <EmergencyStep onAnswer={(e) => { setUrgency(e ? 'emergency' : 'routine'); setStep('care') }} />}
        {step === 'care' && <CareStep services={cfg?.services ?? []} onPick={(k) => { setService(k); if (payload && last.current) run({ ...last.current, service: k }); else setStep('where') }} />}
        {step === 'where' && (
          <WhereStep loc={loc} onLoc={setLoc} onGo={go} urgency={urgency} onUrgency={setUrgency} showUrgency={role !== 'patient'} busy={busy} />
        )}
        {step === 'result' && payload && (
          <ResultView payload={payload} role={role} onOpen={setDrawer} onClarify={onClarify}
                      onEditPlace={() => setStep('where')} onEditCare={() => setStep('care')} onMove={onMove} />
        )}
        {busy && step !== 'result' && <div className="loading" role="status">Finding the best options…</div>}
      </main>

      <footer className="foot muted small">{T.footer}</footer>
      <VoiceSheet enabled={!!cfg?.livekit_enabled} role={role} onResult={onVoiceResult} />
      {drawer && payload?.status === 'ok' && (
        <WhyHowDrawer rec={drawer} payload={payload} weights={weights} onWeights={onWeights} onClose={() => setDrawer(null)} />
      )}
    </div>
  )
}
