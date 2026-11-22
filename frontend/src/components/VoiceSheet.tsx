import '@livekit/components-styles'
import {
  BarVisualizer, LiveKitRoom, RoomAudioRenderer, useRoomContext, useTextStream, useTranscriptions, useVoiceAssistant,
} from '@livekit/components-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { voiceToken, type VoiceToken } from '../api'
import { T } from '../strings'
import type { Payload, Role } from '../types'

const RESULT_TOPIC = 'care-finder.result'
interface Typed { id: string; text: string; ts: number }

function Session({ onResult, onEnd, minimized, onToggle }: {
  onResult: (p: Payload) => void; onEnd: () => void; minimized: boolean; onToggle: () => void
}) {
  const room = useRoomContext()
  const { state, audioTrack } = useVoiceAssistant()
  const transcripts = useTranscriptions()
  const { textStreams } = useTextStream(RESULT_TOPIC)
  const [typed, setTyped] = useState<Typed[]>([])
  const [draft, setDraft] = useState('')
  const seen = useRef(0)
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (textStreams.length > seen.current) {
      seen.current = textStreams.length
      try { onResult(JSON.parse(textStreams[textStreams.length - 1].text) as Payload) } catch { /* stream still arriving */ }
    }
  }, [textStreams, onResult])

  const me = room.localParticipant.identity
  const lines = useMemo(() => {
    const spoken = transcripts.map((t) => ({ id: t.streamInfo.id, who: t.participantInfo.identity === me ? 'me' : 'agent', text: t.text, ts: t.streamInfo.timestamp }))
    return [...spoken, ...typed.map((t) => ({ ...t, who: 'me' }))].filter((l) => l.text.trim()).sort((a, b) => a.ts - b.ts)
  }, [transcripts, typed, me])
  useEffect(() => end.current?.scrollIntoView({ block: 'nearest' }), [lines.length, minimized])

  const send = async (e: FormEvent) => {
    e.preventDefault()
    const text = draft.trim()
    if (!text) return
    setDraft('')
    setTyped((t) => [...t, { id: `typed-${Date.now()}`, text, ts: Date.now() }])
    await room.localParticipant.sendText(text, { topic: 'lk.chat' })
  }
  const stop = () => { room.disconnect(); onEnd() }

  if (minimized) {
    return (
      <button className="voice-pill" onClick={onToggle} aria-label="Open the conversation">
        <span className={`pill-dot pill-${state}`} aria-hidden="true" /> {T.states[state] ?? state} · tap to open
      </button>
    )
  }
  return (
    <div className="sheet" role="dialog" aria-label="Talk to Care Finder">
      <div className="sheet-head">
        <div className={`orb orb-${state}`} aria-hidden="true"><BarVisualizer state={state} trackRef={audioTrack} barCount={5} className="viz" /></div>
        <div className="sheet-state">
          <strong aria-live="polite">{T.states[state] ?? state}</strong>
          <span className="muted small">Say what care is needed and where. You can type too.</span>
        </div>
        <button className="btn btn-ghost" onClick={onToggle} aria-label="Minimise">▾</button>
        <button className="btn btn-danger" onClick={stop}>End</button>
      </div>
      <div className="convo" aria-live="polite">
        {lines.length === 0 && <p className="muted">Listening… try “My mother needs dialysis, we are in Bandra, Mumbai.”</p>}
        {lines.map((l) => <div key={l.id} className={`bubble bubble-${l.who}`}>{l.text}</div>)}
        <div ref={end} />
      </div>
      <form className="chat" onSubmit={send}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={T.typeMessage} aria-label={T.typeMessage} />
        <button className="btn btn-primary" disabled={!draft.trim()}>{T.send}</button>
      </form>
    </div>
  )
}

/** Floating mic on every step. Opens a voice (or typing) session with the same agent as the phone line. */
export function VoiceSheet({ enabled, role, onResult }: { enabled: boolean; role: Role | null; onResult: (p: Payload) => void }) {
  const [tok, setTok] = useState<VoiceToken | null>(null)
  const [mode, setMode] = useState<'voice' | 'text'>('voice')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [min, setMin] = useState(false)

  const start = async (m: 'voice' | 'text') => {
    setErr(null); setBusy(true); setMode(m); setMin(false)
    try { setTok(await voiceToken(role)) } catch { setErr(T.voiceDown) } finally { setBusy(false) }
  }
  const handleResult = (p: Payload) => { onResult(p); setMin(true) }

  if (!enabled) return null
  if (!tok) {
    return (
      <div className="fab-wrap">
        {err && <div className="note note-warn">{err}</div>}
        <button className="link small" onClick={() => start('text')} disabled={busy}>Type to the assistant</button>
        <button className="fab" onClick={() => start('voice')} disabled={busy} aria-label="Talk to Care Finder">
          <span aria-hidden="true">{busy ? '…' : '🎙'}</span><span className="fab-label">{busy ? 'Connecting' : 'Talk'}</span>
        </button>
      </div>
    )
  }
  return (
    <LiveKitRoom serverUrl={tok.server_url} token={tok.participant_token} connect audio={mode === 'voice'} video={false}
                 onDisconnected={() => setTok(null)} onMediaDeviceFailure={() => { setErr(T.micBlocked); setMode('text') }}>
      <RoomAudioRenderer />
      <Session onResult={handleResult} onEnd={() => setTok(null)} minimized={min} onToggle={() => setMin((m) => !m)} />
    </LiveKitRoom>
  )
}
