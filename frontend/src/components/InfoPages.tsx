import type { Config } from '../types'
import { IconAlert, IconArrowRight, IconDatabase, IconMic, IconShieldCheck, IconSliders } from './Icons'

export type InfoTab = 'methodology' | 'about' | 'policy'

export function InfoPages({
  tab,
  cfg,
  onStartSearch,
}: {
  tab: InfoTab
  cfg: Config | null
  onStartSearch: () => void
}) {
  const rawRecords = cfg?.funnel_base?.raw_records?.toLocaleString('en-IN') ?? '10,088'
  const uniqueRecords = cfg?.funnel_base?.unique_records?.toLocaleString('en-IN') ?? '10,077'
  const usableRecords = cfg?.funnel_base?.usable_records?.toLocaleString('en-IN') ?? '9,698'

  if (tab === 'methodology') {
    return (
      <article className="info-page">
        <header className="info-hero">
          <span className="kicker">Clinical Verification Engine</span>
          <h1>How Care Finder evaluates &amp; ranks facilities</h1>
          <p className="muted">
            Every recommendation passes a strict two-stage pipeline: deterministic safety gates first, followed by transparent multi-factor scoring. No facility is ever invented by a language model.
          </p>
        </header>

        <section className="info-section">
          <h2>1 · Five hard clinical gates</h2>
          <p className="muted">
            Before any ranking weights are applied, a facility must pass every gate below. Even if a user drags the Distance slider to 100%, an unverified or mismatched facility will never surface.
          </p>
          <div className="info-grid-2">
            <div className="info-card">
              <div className="info-card-num">Gate 01</div>
              <h3>Direct facility-level evidence</h3>
              <p className="muted small">
                The requested service must appear explicitly in the facility’s own <code>procedure</code>, <code>equipment</code>, <code>capability</code>, or <code>description</code> fields — not merely an inferred broad specialty.
              </p>
            </div>
            <div className="info-card">
              <div className="info-card-num">Gate 02</div>
              <h3>Third-party listing exclusion</h3>
              <p className="muted small">
                Extracted web snippets that describe another hospital or generic referral directory text are flagged and excluded so merged records cannot mislead patients.
              </p>
            </div>
            <div className="info-card">
              <div className="info-card-num">Gate 03</div>
              <h3>Record trust ≥ 0.50</h3>
              <p className="muted small">
                Records are penalized for contradictory coordinates vs. India Post PIN centroids, single thin web sources, or shifted/corrupted schema fields.
              </p>
            </div>
            <div className="info-card">
              <div className="info-card-num">Gate 04 &amp; 05</div>
              <h3>Facility-type fit &amp; travel radius</h3>
              <p className="muted small">
                Clinical plausibility (e.g., an eye clinic or dental practice cannot pass for NICU or dialysis) and service-specific travel decay radius (<code>τ × 3</code> routine, <code>τ × 2</code> emergency).
              </p>
            </div>
          </div>
        </section>

        <section className="info-section">
          <h2>2 · Weighted scoring &amp; three distinct tiers</h2>
          <div className="formula-banner">
            <code>score = w₁·proximity + w₂·evidence + w₃·trust + w₄·depth</code>
            <span className="muted small">where proximity = exp(−km / τ) and evidence = evidence_score × type_fit</span>
          </div>
          <div className="info-grid-3">
            <div className="info-card">
              <span className="tier-label">Tier 1</span>
              <h3>Best balanced</h3>
              <p className="muted small">
                Highest combined score across distance, verified evidence strength, record trust, and clinical depth (beds, doctors, specific unit claims).
              </p>
            </div>
            <div className="info-card">
              <span className="tier-label">Tier 2</span>
              <h3>Nearest verified</h3>
              <p className="muted small">
                Closest facility passing all five gates (prioritizing Medium or High confidence), ideal when travel time is the dominant clinical risk.
              </p>
            </div>
            <div className="info-card">
              <span className="tier-label">Tier 3</span>
              <h3>Highest-confidence</h3>
              <p className="muted small">
                Strongest corroborated evidence and record trust within the search radius, regardless of extra travel distance.
              </p>
            </div>
          </div>
        </section>

        <section className="info-section">
          <h2>3 · Confidence rubric &amp; care desert detection</h2>
          <div className="rubric-table">
            <div className="rubric-row">
              <span className="chip chip-high">High</span>
              <span>Two or more independent text fields corroborate the service (<code>evidence ≥ 0.75</code>), <code>trust ≥ 0.75</code>, and facility type fits cleanly.</span>
            </div>
            <div className="rubric-row">
              <span className="chip chip-medium">Medium</span>
              <span>Direct evidence exists (<code>evidence ≥ 0.50</code>) with acceptable trust (<code>≥ 0.50</code>), typically from a single field — phone confirmation recommended.</span>
            </div>
            <div className="rubric-row">
              <span className="chip chip-low">Low</span>
              <span>Sparse corroboration or caution flags present. Shown only when stronger options are unavailable, always with explicit call-ahead notices.</span>
            </div>
          </div>
          <p className="muted small mt-3">
            When zero verified facilities exist within a service’s safe travel scale (<code>τ</code>), Care Finder triggers a <strong>Care Desert Alert</strong>, draws the safe-distance boundary on the map, expands search up to 600 km to identify the nearest verified option, and reminds callers to also contact their district public hospital.
          </p>
        </section>

        <div className="info-cta">
          <button type="button" className="btn btn-primary" onClick={onStartSearch}>
            <span>Launch Care Finder</span>
            <IconArrowRight size={16} />
          </button>
        </div>
      </article>
    )
  }

  if (tab === 'about') {
    return (
      <article className="info-page">
        <header className="info-hero">
          <span className="kicker">About Care Finder</span>
          <h1>Closing the verified referral gap across India</h1>
          <p className="muted">
            Built to help community health workers (ASHAs), NGO coordinators, clinicians, and families answer one urgent question: <em>where should this patient go for specialized care, and why should we trust that answer?</em>
          </p>
        </header>

        <section className="info-section">
          <div className="info-grid-3">
            <div className="info-card">
              <span className="info-icon"><IconDatabase size={20} /></span>
              <h3>Grounded Lakehouse Data</h3>
              <p className="muted small">
                Curated from {rawRecords} raw Virtue Foundation facility records ({uniqueRecords} deduplicated, {usableRecords} geospatially validated), cross-referenced against 165,627 India Post PIN centroids and 706 NFHS-5 district health indicators.
              </p>
            </div>
            <div className="info-card">
              <span className="info-icon"><IconMic size={20} /></span>
              <h3>Multilingual Voice &amp; Phone Access</h3>
              <p className="muted small">
                Designed for low-literacy and low-bandwidth contexts: callers can speak in English, Hindi, Marathi, Bengali, Tamil, Telugu, and other Indian languages via browser voice or direct phone helpline.
              </p>
            </div>
            <div className="info-card">
              <span className="info-icon"><IconSliders size={20} /></span>
              <h3>Radical Explainability</h3>
              <p className="muted small">
                Every card displays verbatim facility quotes, clickable web provenance, location conflict cautions, skipped closer facilities, and interactive weight sliders backed by real-time DuckDB serving.
              </p>
            </div>
          </div>
        </section>

        <section className="info-section">
          <h2>Platform Architecture</h2>
          <div className="info-card">
            <ul className="plain-list">
              <li>
                <strong>Data Pipeline (Databricks Unity Catalog):</strong> Bronze → Silver → Gold Delta tables normalize Indian state spellings, detect merged/corrupted records, extract service-level evidence snippets, and export serving Parquet snapshots.
              </li>
              <li>
                <strong>Decision Engine (FastAPI + DuckDB):</strong> Sub-50ms deterministic geographic &amp; clinical gate evaluation running inside a unified Databricks App container.
              </li>
              <li>
                <strong>Voice &amp; Live Monitor (LiveKit + Gemini Live):</strong> Real-time WebRTC audio and SIP telephony bound strictly to a single grounded tool (<code>find_best_care</code>), with live visual mirroring on <code>/monitor</code>.
              </li>
            </ul>
          </div>
        </section>

        <div className="info-cta">
          <button type="button" className="btn btn-primary" onClick={onStartSearch}>
            <span>Start a verified lookup</span>
            <IconArrowRight size={16} />
          </button>
        </div>
      </article>
    )
  }

  // Clinical & Data Policy
  return (
    <article className="info-page">
      <header className="info-hero">
        <span className="kicker">Clinical Governance &amp; Privacy</span>
        <h1>Clinical Disclaimer, Data Limitations &amp; Privacy Policy</h1>
        <p className="muted">
          Effective November 2026 · Care Finder Decision-Support Standards
        </p>
      </header>

      <section className="info-section">
        <div className="notice notice-warn">
          <IconAlert size={18} />
          <span>
            <strong>Not medical advice or diagnosis.</strong> Care Finder is a healthcare navigation and directory-verification aid. It does not diagnose conditions, guarantee live bed/equipment availability, or substitute for licensed clinical judgment. In any life-threatening emergency in India, dial <strong>108</strong> immediately.
          </span>
        </div>
      </section>

      <section className="info-section info-prose">
        <div className="info-card">
          <div className="policy-head">
            <IconShieldCheck size={18} />
            <h3>1. Grounding &amp; Zero-Hallucination Standard</h3>
          </div>
          <p className="muted small">
            Care Finder’s web interface and voice assistant are strictly constrained to facilities returned by the deterministic backend engine. Neither the UI nor the voice agent may fabricate hospital names, phone numbers, bed counts, clinical capabilities, or distances. Every surfaced claim is accompanied by its verbatim source field and confidence tier.
          </p>
        </div>

        <div className="info-card">
          <h3>2. Dataset Coverage &amp; Known Limitations</h3>
          <p className="muted small">
            Facility records originate primarily from the Virtue Foundation web-extracted dataset and public Indian directories. Because public/government facilities (PHCs, CHCs, and District Hospitals) are often under-represented online, a “Care Desert” alert reflects absence of verified records <em>in this dataset</em>—not necessarily complete absence of local public care. Always confirm active equipment, specialist staffing, and insurance acceptance (e.g., PM-JAY / Ayushman Bharat) by phone before travelling.
          </p>
        </div>

        <div className="info-card">
          <h3>3. Privacy &amp; Voice Session Handling</h3>
          <p className="muted small">
            Manual searches require only a care category and approximate location (PIN, town, or GPS coordinates); no patient name, Aadhaar number, or personal health identifier (PHI) is requested or stored. Browser voice sessions use ephemeral, 15-minute scoped LiveKit room tokens. Callers are advised not to share personally identifiable medical records during voice inquiries.
          </p>
        </div>

        <div className="info-card">
          <h3>4. Corrections &amp; Institutional Inquiries</h3>
          <p className="muted small">
            Hospital administrators, NGOs, and district health planners wishing to update facility coordinates, phone numbers, or service capabilities can submit corrections through the Virtue Foundation open-data stewardship channel or partner Databricks Lakehouse feed.
          </p>
        </div>
      </section>

      <div className="info-cta">
        <button type="button" className="btn btn-primary" onClick={onStartSearch}>
          <span>Return to Care Finder</span>
          <IconArrowRight size={16} />
        </button>
      </div>
    </article>
  )
}
