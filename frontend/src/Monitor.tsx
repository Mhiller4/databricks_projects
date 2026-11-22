import { useEffect, useState } from 'react'
import { liveSocketUrl } from './api'
import { ResultView } from './components/ResultView'
import { WhyHowDrawer } from './components/WhyHowDrawer'
import { T } from './strings'
import type { Payload, Rec, Role, Weights } from './types'

// Big-screen view for phone-call demos: the latest voice search from any session (WS /ws/live).
export default function Monitor() {
  const [payload, setPayload] = useState<Payload | null>(null)
  const [meta, setMeta] = useState<{ source?: string; audience?: Role | null; at?: Date }>({})
  const [drawer, setDrawer] = useState<Rec | null>(null)
  const [live, setLive] = useState(false)

  useEffect(() => {
    let ws: WebSocket | null = null
    let stop = false
    let ping: number | undefined
    const connect = () => {
      ws = new WebSocket(liveSocketUrl())
      ws.onopen = () => { setLive(true); ping = window.setInterval(() => ws?.readyState === 1 && ws.send('ping'), 25000) }
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data)
        if (m.type === 'recommendation') { setPayload(m.payload); setMeta({ source: m.source, audience: m.audience, at: new Date() }) }
      }
      ws.onclose = () => { setLive(false); window.clearInterval(ping); if (!stop) setTimeout(connect, 2000) }
    }
    connect()
    return () => { stop = true; ws?.close() }
  }, [])

  const w = (payload?.query.weights ?? { proximity: 0.35, evidence: 0.3, trust: 0.2, depth: 0.15 }) as unknown as Weights
  return (
    <div className="app">
      <header className="bar">
        <a className="brand" href="/"><span className="logo" aria-hidden="true">+</span><span><strong>{T.monitorTitle}</strong>
          <span className="muted small">{live ? '● live' : '○ reconnecting…'}{meta.at ? ` · last search ${meta.at.toLocaleTimeString()} · ${meta.audience ?? 'caller'} via ${meta.source}` : ''}</span></span></a>
      </header>
      <main className="main wide">
        {!payload && <div className="loading">{T.monitorWaiting}</div>}
        {payload?.spoken_summary && <div className="said"><span className="muted small">What the agent said</span><p>{payload.spoken_summary}</p></div>}
        {payload && <ResultView payload={payload} role={meta.audience ?? 'provider'} onOpen={setDrawer} />}
      </main>
      {drawer && payload?.status === 'ok' && <WhyHowDrawer rec={drawer} payload={payload} weights={w} onWeights={() => {}} onClose={() => setDrawer(null)} />}
    </div>
  )
}
