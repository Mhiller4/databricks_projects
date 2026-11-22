import type { Confidence } from '../types'

export const CONFIDENCE_WORDS: Record<Confidence, string> = {
  High: 'Strong evidence they offer this',
  Medium: 'Likely offers this: confirm by phone',
  Low: 'Unclear: confirm by phone before going',
}

export function ConfidenceChip({ c }: { c: string }) {
  return <span className={`chip chip-${c.toLowerCase()}`}>{c} confidence</span>
}

export const km = (d: number) => (d < 1 ? 'under 1 km' : `${d.toFixed(d < 10 ? 1 : 0)} km`)

export const directionsUrl = (lat: number, lon: number) => `https://www.google.com/maps/dir/?api=1&destination=${lat},${lon}`

export const telHref = (p: string) => `tel:${p.replace(/[^\d+]/g, '')}`
