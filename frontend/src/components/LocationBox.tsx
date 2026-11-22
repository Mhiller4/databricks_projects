import { useEffect, useRef, useState } from 'react'
import { suggest } from '../api'
import { T } from '../strings'
import type { Suggestion } from '../types'
import { IconGps, IconPin, IconX } from './Icons'

export interface LocValue {
  query: string | { lat: number; lon: number }
  label: string
  precise: boolean | null
}

export function LocationBox({
  value,
  onChange,
  onGpsPick,
  label = T.location,
  showGps = true,
  autoFocus = false,
  compact = false,
  id = 'loc-input',
}: {
  value: LocValue
  onChange: (v: LocValue) => void
  onGpsPick?: (v: LocValue) => void
  label?: string | null
  showGps?: boolean
  autoFocus?: boolean
  compact?: boolean
  id?: string
}) {
  const [text, setText] = useState(value.label)
  const [items, setItems] = useState<Suggestion[]>([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [locating, setLocating] = useState(false)
  const [gpsError, setGpsError] = useState<string | null>(null)
  const abort = useRef<AbortController | null>(null)

  useEffect(() => setText(value.label), [value.label])

  useEffect(() => {
    const q = text.trim()
    const picked = value.precise !== null && q === value.label
    if (q.length < 2 || picked) {
      setItems([])
      return
    }
    const t = setTimeout(() => {
      abort.current?.abort()
      abort.current = new AbortController()
      suggest(q, abort.current.signal)
        .then((r) => {
          setItems(r)
          setActive(-1)
          setOpen(true)
        })
        .catch(() => {})
    }, 170)
    return () => clearTimeout(t)
  }, [text, value.label, value.precise])

  const pick = (s: Suggestion) => {
    const next: LocValue = {
      query: s.query,
      label: s.display_name.replace(' (post office)', ''),
      precise: s.is_precise,
    }
    onChange(next)
    setOpen(false)
  }

  const clear = () => {
    setText('')
    setItems([])
    onChange({ query: '', label: '', precise: null })
  }

  const gps = () => {
    setGpsError(null)
    if (!navigator.geolocation) {
      setGpsError('Browser geolocation unavailable. Enter a 6-digit PIN or locality.')
      return
    }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setLocating(false)
        const v: LocValue = {
          query: { lat: p.coords.latitude, lon: p.coords.longitude },
          label: 'Current location (GPS)',
          precise: true,
        }
        onChange(v)
        onGpsPick?.(v)
      },
      () => {
        setLocating(false)
        setGpsError('Could not read GPS. Enter a PIN code, town, or locality.')
      },
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  const listId = `${id}-list`

  return (
    <div className={`locbox ${compact ? 'locbox-compact' : ''}`}>
      {label && (
        <label className="field-label" htmlFor={id}>
          {label}
        </label>
      )}
      <div className="locbox-row">
        <div className="combo">
          <span className="input-icon">
            <IconPin size={16} />
          </span>
          <input
            id={id}
            autoFocus={autoFocus}
            aria-label={label ?? T.location}
            role="combobox"
            aria-expanded={open && items.length > 0}
            aria-controls={listId}
            autoComplete="off"
            placeholder={T.locationPlaceholder}
            value={text}
            className="has-icon-left has-icon-right"
            onChange={(e) => {
              setText(e.target.value)
              onChange({ query: e.target.value, label: e.target.value, precise: null })
            }}
            onFocus={() => items.length && setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 160)}
            onKeyDown={(e) => {
              if (!open || !items.length) return
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setActive((a) => Math.min(a + 1, items.length - 1))
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault()
                setActive((a) => Math.max(a - 1, 0))
              }
              if (e.key === 'Enter' && active >= 0) {
                e.preventDefault()
                pick(items[active])
              }
              if (e.key === 'Escape') setOpen(false)
            }}
          />
          {text && (
            <button
              type="button"
              className="input-clear"
              onClick={clear}
              aria-label="Clear location"
              title="Clear"
            >
              <IconX size={14} />
            </button>
          )}
          {open && items.length > 0 && (
            <ul id={listId} className="combo-list" role="listbox">
              {items.map((s, i) => (
                <li
                  key={`${s.kind}-${s.display_name}-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={i === active ? 'active' : ''}
                  onMouseDown={() => pick(s)}
                >
                  <span className="combo-name">{s.display_name.replace(' (post office)', '')}</span>
                  <span className="combo-kind">{s.kind === 'post_office' ? 'locality' : s.kind}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        {showGps && (
          <button
            type="button"
            className="btn btn-soft gps-btn"
            onClick={gps}
            disabled={locating}
            title={T.useMyLocation}
          >
            <IconGps size={16} />
            <span>{locating ? 'Locating…' : T.useMyLocation}</span>
          </button>
        )}
      </div>
      {!compact && value.precise !== null && (
        <div className={`precision-pill ${value.precise ? 'precision-ok' : 'precision-warn'}`}>
          {value.precise ? `✓ ${T.precise}` : `⚠ ${T.rough}`}
        </div>
      )}
      {gpsError && <div className="notice notice-warn">{gpsError}</div>}
    </div>
  )
}
