import '@livekit/components-styles'
import {
  BarVisualizer,
  LiveKitRoom,
  RoomAudioRenderer,
  useLocalParticipant,
  useRoomContext,
  useTextStream,
  useTranscriptions,
  useVoiceAssistant,
} from '@livekit/components-react'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { voiceToken, type VoiceToken } from '../api'
import { T } from '../strings'
import type { Payload, Role } from '../types'
import { IconChevronDown, IconMic, IconMicOff, IconSend, IconX } from './Icons'

const RESULT_TOPIC = 'care-finder.result'
interface Typed {
  id: string
  text: string
  ts: number
}

const FOLLOWUPS = [
  'Why not a closer facility?',
  'What is their phone number?',
  'Read a referral note',
]

function Session({
  onResult,
  onEnd,
  minimized,
  onToggle,
}: {
  onResult: (p: Payload) => void
  onEnd: () => void
  minimized: boolean
  onToggle: () => void
}) {
  const room = useRoomContext()
  const { localParticipant, isMicrophoneEnabled } = useLocalParticipant()
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
      try {
        onResult(JSON.parse(textStreams[textStreams.length - 1].text) as Payload)
      } catch {
        /* stream still arriving */
      }
    }
  }, [textStreams, onResult])

  const me = room.localParticipant.identity
  const lines = useMemo(() => {
    const spoken = transcripts.map((t) => ({
      id: t.streamInfo.id,
      who: t.participantInfo.identity === me ? 'me' : 'agent',
      text: t.text,
      ts: t.streamInfo.timestamp,
    }))
    return [...spoken, ...typed.map((t) => ({ ...t, who: 'me' }))]
      .filter((l) => l.text.trim())
      .sort((a, b) => a.ts - b.ts)
  }, [transcripts, typed, me])

  useEffect(() => end.current?.scrollIntoView({ block: 'nearest' }), [lines.length, minimized])

  const sendText = async (text: string) => {
    const clean = text.trim()
    if (!clean) return
    setTyped((t) => [...t, { id: `typed-${Date.now()}`, text: clean, ts: Date.now() }])
    await room.localParticipant.sendText(clean, { topic: 'lk.chat' })
  }

  const send = async (e: FormEvent) => {
    e.preventDefault()
    if (!draft.trim()) return
    const next = draft
    setDraft('')
    await sendText(next)
  }

  const toggleMic = () => {
    localParticipant.setMicrophoneEnabled(!isMicrophoneEnabled).catch(() => {})
  }

  const stop = () => {
    room.disconnect()
    onEnd()
  }

  if (minimized) {
    return (
      <button type="button" className="voice-pill" onClick={onToggle} aria-label="Open assistant conversation">
        <span className={`pill-dot pill-${state}`} aria-hidden="true" />
        <span>{T.states[state] ?? state} · Open assistant</span>
      </button>
    )
  }

  return (
    <div className="sheet" role="dialog" aria-label="Care Finder Assistant">
      <div className="sheet-head">
        <div className={`orb orb-${state}`} aria-hidden="true">
          <BarVisualizer state={state} trackRef={audioTrack} barCount={5} className="viz" />
        </div>
        <div className="sheet-state">
          <strong aria-live="polite">{T.states[state] ?? state}</strong>
          <span className="muted small">Speak naturally or type below — answers cite verified records.</span>
        </div>
        <button
          type="button"
          className={`icon-btn ${!isMicrophoneEnabled ? 'icon-btn-muted' : ''}`}
          onClick={toggleMic}
          aria-label={isMicrophoneEnabled ? 'Mute microphone' : 'Unmute microphone'}
          title={isMicrophoneEnabled ? 'Mute mic' : 'Unmute mic'}
        >
          {isMicrophoneEnabled ? <IconMic size={17} /> : <IconMicOff size={17} />}
        </button>
        <button type="button" className="icon-btn" onClick={onToggle} aria-label="Minimise assistant">
          <IconChevronDown size={17} />
        </button>
        <button type="button" className="btn btn-danger btn-xs" onClick={stop}>
          <IconX size={14} />
          <span>End</span>
        </button>
      </div>

      <div className="convo" aria-live="polite">
        {lines.length === 0 && (
          <p className="muted small convo-empty">
            Listening… try “My mother needs dialysis near Bandra, Mumbai.”
          </p>
        )}
        {lines.map((l) => (
          <div key={l.id} className={`bubble bubble-${l.who}`}>
            {l.text}
          </div>
        ))}
        <div ref={end} />
      </div>

      {lines.length > 0 && (
        <div className="followup-row">
          {FOLLOWUPS.map((f) => (
            <button key={f} type="button" className="followup-chip" onClick={() => sendText(f)}>
              {f}
            </button>
          ))}
        </div>
      )}

      <form className="chat" onSubmit={send}>
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={T.typeMessage}
          aria-label={T.typeMessage}
        />
        <button className="btn btn-primary btn-sm" disabled={!draft.trim()} aria-label={T.send}>
          <IconSend size={15} />
          <span className="hide-xs">{T.send}</span>
        </button>
      </form>
    </div>
  )
}

export interface VoiceTrigger {
  mode: 'voice' | 'text'
  seq: number
}

/** Voice + Chat assistant sheet backed by LiveKit. Triggerable externally or via floating FAB. */
export function VoiceSheet({
  enabled,
  role,
  onResult,
  trigger,
  showFab = true,
}: {
  enabled: boolean
  role: Role | null
  onResult: (p: Payload) => void
  trigger?: VoiceTrigger | null
  showFab?: boolean
}) {
  const [tok, setTok] = useState<VoiceToken | null>(null)
  const [mode, setMode] = useState<'voice' | 'text'>('voice')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [min, setMin] = useState(false)
  const lastSeq = useRef(0)

  const start = async (m: 'voice' | 'text') => {
    setErr(null)
    if (tok) {
      setMin(false)
      return
    }
    setBusy(true)
    setMode(m)
    setMin(false)
    try {
      setTok(await voiceToken(role))
    } catch {
      setErr(T.voiceDown)
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    if (trigger && trigger.seq !== lastSeq.current) {
      lastSeq.current = trigger.seq
      start(trigger.mode)
    }
  }, [trigger]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleResult = (p: Payload) => {
    onResult(p)
    setMin(true)
  }

  if (!enabled) return null
  if (!tok) {
    if (!showFab && !err) return null
    return (
      <div className="fab-wrap">
        {err && <div className="notice notice-warn fab-err">{err}</div>}
        {showFab && (
          <button
            type="button"
            className="fab"
            onClick={() => start('voice')}
            disabled={busy}
            aria-label="Talk to Care Finder"
          >
            <IconMic size={19} />
            <span>{busy ? 'Connecting…' : T.tapToTalk}</span>
          </button>
        )}
      </div>
    )
  }

  return (
    <LiveKitRoom
      serverUrl={tok.server_url}
      token={tok.participant_token}
      connect
      audio={mode === 'voice'}
      video={false}
      onDisconnected={() => setTok(null)}
      onMediaDeviceFailure={() => {
        setErr(T.micBlocked)
        setMode('text')
      }}
    >
      <RoomAudioRenderer />
      <Session
        onResult={handleResult}
        onEnd={() => setTok(null)}
        minimized={min}
        onToggle={() => setMin((m) => !m)}
      />
    </LiveKitRoom>
  )
}
