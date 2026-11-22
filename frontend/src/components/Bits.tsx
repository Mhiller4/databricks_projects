import type { Confidence, Payload, Rec } from '../types'
import { IconShieldCheck } from './Icons'

export const CONFIDENCE_WORDS: Record<Confidence, string> = {
  High: 'Several parts of their record mention it',
  Medium: 'Probably offered. Call to confirm.',
  Low: 'Little evidence. Call before you go.',
}

export function ConfidenceChip({ c }: { c: string }) {
  return (
    <span className={`chip chip-${c.toLowerCase()}`}>
      <IconShieldCheck size={13} />
      <span>{c}</span>
    </span>
  )
}

export const km = (d: number) => (d < 1 ? '< 1 km' : `${d.toFixed(d < 10 ? 1 : 0)} km`)

export const directionsUrl = (lat: number, lon: number) =>
  `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`

export const telHref = (p: string) => `tel:${p.replace(/[^\d+]/g, '')}`

export function buildReferral(r: Rec, p: Payload): string {
  const svc = typeof p.query.service === 'string' ? p.query.service : p.query.service.label
  const loc = p.query.location as { display_name?: string }
  const where = loc?.display_name?.replace(' (post office)', '') ?? 'specified location'
  const date = new Date().toISOString().slice(0, 10)
  return [
    `Referral · ${svc}`,
    `${r.name}${r.facility_type ? ` (${r.facility_type})` : ''} · ${km(r.distance_km)} from ${where}`,
    `Address: ${r.address ?? 'not listed'} · Phone: ${r.phone ?? 'not listed'}`,
    `Why: ${r.why[0] ?? 'Passes all five care.in checks.'}`,
    `Confidence: ${r.confidence}. ${r.confidence_reason}`,
    `Cautions: ${r.cautions.length ? r.cautions.join('; ') : 'none listed'}`,
    `Source: care.in (Virtue Foundation dataset, ${date}) · call ahead before travelling`,
  ].join('\n')
}

export const whatsappUrl = (text: string) => `https://wa.me/?text=${encodeURIComponent(text)}`
