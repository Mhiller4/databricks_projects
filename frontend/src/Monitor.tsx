import { useEffect, useState } from 'react'
import { liveSocketUrl } from './api'
import { IconPlus } from './components/Icons'
import { ResultView } from './components/ResultView'
import { WhyHowDrawer } from './components/WhyHowDrawer'
import { T } from './strings'
import type { Payload, Rec, Role, Weights } from './types'

// Big-screen view for phone-call demos: streams the latest voice search over WS /ws/live.
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
      ws.onopen = () => {
        setLive(true)
        ping = window.setInterval(() => ws?.readyState === 1 && ws.send('ping'), 25000)
      }
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data)
        if (m.type === 'recommendation') {
          setPayload(m.payload)
          setMeta({ source: m.source, audience: m.audience, at: new Date() })
        }
      }
      ws.onclose = () => {
        setLive(false)
        window.clearInterval(ping)
        if (!stop) setTimeout(connect, 2000)
      }
    }
    connect()
    return () => {
      stop = true
      ws?.close()
    }
  }, [])

  const w = (payload?.query.weights ?? {
    proximity: 0.35,
    evidence: 0.3,
    trust: 0.2,
    depth: 0.15,
  }) as unknown as Weights

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <a className="brand" href="/">
            <span className="logo">
              <IconPlus size={18} />
            </span>
            <span className="brand-text">
              <strong>{T.monitorTitle}</strong>
              <span className="brand-sub">
                <span className={`live-dot ${live ? 'on' : ''}`} />
                {live ? 'Live stream connected' : 'Reconnecting…'}
                {meta.at
                  ? ` · ${meta.at.toLocaleTimeString()} · ${meta.audience ?? 'caller'} via ${meta.source}`
                  : ''}
              </span>
            </span>
          </a>
          <div className="bar-right">
            <a className="btn btn-ghost btn-sm" href="/">
              ← Back to Care Finder
            </a>
          </div>
        </div>
      </header>

      <main className="main main-wide">
        {!payload && (
          <div className="narrow-state">
            <div className="state-card">
              <span className="kicker">Phone &amp; Voice Telemetry</span>
              <h2>{T.monitorWaiting}</h2>
              <p className="muted small">
                When a caller or web voice session queries Care Finder, the grounded map, tiered facility cards, and spoken summary appear here automatically.
              </p>
            </div>
          </div>
        )}
        {payload?.spoken_summary && (
          <div className="said-banner">
            <span className="kicker">Spoken response</span>
            <p>{payload.spoken_summary}</p>
          </div>
        )}
        {payload && (
          <ResultView
            payload={payload}
            role={meta.audience ?? 'provider'}
            onOpen={setDrawer}
          />
        )}
      </main>

      {drawer && payload?.status === 'ok' && (
        <WhyHowDrawer
          rec={drawer}
          payload={payload}
          weights={w}
          onWeights={() => {}}
          onClose={() => setDrawer(null)}
          readOnlyWeights
        />
      )}
    </div>
  )
}
