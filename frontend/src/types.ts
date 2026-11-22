// Shapes returned by the backend (backend/app/engine.py). Only the fields the page uses are typed.

export type Confidence = 'High' | 'Medium' | 'Low'
export type Role = 'provider' | 'patient'

export interface Citation { field: string; text: string; third_party: boolean; source_table: string }

export interface ScoreBreakdown {
  components: Record<string, number>
  weights: Record<string, number>
  contributions: Record<string, number>
  formula: string
  raw: { evidence_score: number; type_fit: number; trust_score: number; tau_km: number; evidence_fields: string[] }
}

export interface Rec {
  tier: string | null
  tier_label: string | null
  tier_reason: string | null
  facility_id: string
  name: string
  facility_type: string | null
  address: string | null
  city: string | null
  district: string | null
  state: string | null
  pin: string | null
  phone: string | null
  website: string | null
  lat: number
  lon: number
  distance_km: number
  score: number
  confidence: Confidence
  confidence_reason: string
  why: string[]
  score_breakdown: ScoreBreakdown
  citations: Citation[]
  source_urls: string[]
  cautions: string[]
  call_ahead: string[]
}

export interface Skipped {
  facility_id: string
  name: string
  facility_type: string | null
  distance_km: number
  lat: number
  lon: number
  confidence: Confidence
  excluded: boolean
  reasons: string[]
  evidence: { field: string; text: string }[]
}

export interface QueryLocation {
  input: unknown
  kind: string
  display_name: string
  district: string | null
  state: string | null
  lat: number
  lon: number
  precision?: string
  is_precise?: boolean
  ask_for_more_detail?: boolean
  more_detail_prompt?: string | null
}

export interface Payload {
  status: 'ok' | 'needs_clarification' | 'unknown_service' | 'unresolved_location' | 'error'
  message?: string
  options?: (string | { display_name: string; query: string; state?: string })[]
  query: {
    service: { input: string; key: string; label: string; tau_km: number } | string
    location: QueryLocation | unknown
    urgency: string
    weights?: Record<string, number>
    radius_km?: number
  }
  method?: { gates: string[]; score: string; confidence_rules: { level: string; rule: string }[] }
  funnel?: { stage: string; count: number }[]
  recommendations?: Rec[]
  nearest_beyond_radius?: Rec[]
  ranked?: Rec[]
  skipped_nearby?: Skipped[]
  medical_desert_alert?: { triggered: boolean; safe_km: number; nearest_verified_km: number | null; nearest_verified_name: string | null; message: string | null }
  spoken_summary?: string
  elapsed_ms?: number
}

export interface Service { key: string; label: string; tau_km: number; synonyms: string[]; note: string }
export interface Config { phone_number: string; services: Service[]; funnel_base: Record<string, number>; livekit_enabled: boolean }
export interface Suggestion {
  kind: string; display_name: string; query: string; district: string | null; state: string | null
  lat: number; lon: number; precision: string; is_precise: boolean
}
export interface Weights { proximity: number; evidence: number; trust: number; depth: number }

export const isOk = (p: Payload | null): p is Payload & { query: { location: QueryLocation; service: { label: string; key: string; tau_km: number } } } =>
  !!p && p.status === 'ok'
