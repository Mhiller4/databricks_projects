import type { Config, Payload, Role, Suggestion, Weights } from './types'

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return r.json() as Promise<T>
}

export const getConfig = () => fetch('/api/config').then((r) => json<Config>(r))

export const suggest = (q: string, signal?: AbortSignal) =>
  fetch(`/api/locations?q=${encodeURIComponent(q)}`, { signal }).then((r) => json<Suggestion[]>(r))

export interface SearchArgs {
  service: string
  location: string | { lat: number; lon: number }
  urgency: 'routine' | 'emergency'
  weights?: Weights | null
  audience?: Role | null
}

export const recommend = (a: SearchArgs) =>
  fetch('/api/recommend', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ...a, weights: a.weights ?? undefined, audience: a.audience ?? undefined, source: 'ui' }),
  }).then((r) => json<Payload>(r))

export interface VoiceToken { server_url: string; participant_token: string; room_name: string; identity: string }

export const voiceToken = (role: Role | null) =>
  fetch('/api/livekit/token', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ role }),
  }).then((r) => json<VoiceToken>(r))

export const liveSocketUrl = () => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/live`
