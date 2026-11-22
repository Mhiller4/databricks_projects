import { useEffect, useRef, useState } from 'react'
import { suggest } from '../api'
import { T } from '../strings'
import type { Suggestion } from '../types'

export interface LocValue {
  query: string | { lat: number; lon: number }
  label: string
  precise: boolean | null
}

export function LocationBox({ value, onChange, label = T.location, showGps = true, autoFocus = false }: {
  value: LocValue; onChange: (v: LocValue) => void; label?: string | null; showGps?: boolean; autoFocus?: boolean
}) {
  const [text, setText] = useState(value.label)
  const [items, setItems] = useState<Suggestion[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [gpsError, setGpsError] = useState<string | null>(null)
  const abort = useRef<AbortController | null>(null)

  useEffect(() => setText(value.label), [value.label])

  useEffect(() => {
    const q = text.trim()
    const picked = value.precise !== null && q === value.label  // just chose a suggestion / GPS: don't reopen the list
    if (q.length < 2 || picked) { setItems([]); return }
    const t = setTimeout(() => {
      abort.current?.abort()
      abort.current = new AbortController()
      suggest(q, abort.current.signal).then((r) => { setItems(r); setActive(-1); setOpen(true) }).catch(() => {})
    }, 180)
    return () => clearTimeout(t)
  }, [text, value.label, value.precise])

  const pick = (s: Suggestion) => {
    onChange({ query: s.query, label: s.display_name.replace(' (post office)', ''), precise: s.is_precise })
    setOpen(false)
  }

  const gps = () => {
    setGpsError(null)
    if (!navigator.geolocation) { setGpsError('Location is not available in this browser.'); return }
    navigator.geolocation.getCurrentPosition(
      (p) => onChange({ query: { lat: p.coords.latitude, lon: p.coords.longitude }, label: 'My location (GPS)', precise: true }),
      () => setGpsError('Could not get your location. Type a PIN or town instead.'),
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  return (
    <div className="locbox">
      {label && <label className="field-label" htmlFor="loc">{label}</label>}
      <div className="locbox-row">
        <div className="combo">
          <input
            id="loc"
            autoFocus={autoFocus}
            aria-label={label ?? T.location}
            role="combobox"
            aria-expanded={open && items.length > 0}
            aria-controls="loc-list"
            autoComplete="off"
            placeholder={T.locationPlaceholder}
            value={text}
            onChange={(e) => { setText(e.target.value); onChange({ query: e.target.value, label: e.target.value, precise: null }) }}
            onFocus={() => items.length && setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            onKeyDown={(e) => {
              if (!open || !items.length) return
              if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)) }
              if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
              if (e.key === 'Enter' && active >= 0) { e.preventDefault(); pick(items[active]) }
              if (e.key === 'Escape') setOpen(false)
            }}
          />
          {open && items.length > 0 && (
            <ul id="loc-list" className="combo-list" role="listbox">
              {items.map((s, i) => (
                <li key={`${s.kind}-${s.display_name}-${i}`} role="option" aria-selected={i === active}
                    className={i === active ? 'active' : ''} onMouseDown={() => pick(s)}>
                  <span className="combo-name">{s.display_name.replace(' (post office)', '')}</span>
                  <span className="combo-kind">{s.kind === 'post_office' ? 'locality' : s.kind}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {showGps && <button type="button" className="btn btn-ghost" onClick={gps} title={T.useMyLocation}>📍 <span className="hide-sm">{T.useMyLocation}</span></button>}
      </div>
      {value.precise !== null && (
        <div className={`badge ${value.precise ? 'badge-ok' : 'badge-warn'}`}>
          {value.precise ? `✓ ${T.precise}` : `⚠ ${T.rough}`}
        </div>
      )}
      {gpsError && <div className="note note-warn">{gpsError}</div>}
    </div>
  )
}
