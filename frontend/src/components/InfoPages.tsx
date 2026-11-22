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
          <span className="kicker">How it works</span>
          <h1>How care.in checks and ranks facilities</h1>
          <p className="muted">
            Each facility first has to pass five checks. The ones that pass are scored and ranked. Every facility
            comes from the dataset; none are made up by an AI model.
          </p>
        </header>

        <section className="info-section">
          <h2>1 · Five checks every facility must pass</h2>
          <p className="muted">
            A facility has to pass all five before it gets a score. Moving the Distance slider to 100% won’t bring
            back one that failed.
          </p>
          <div className="info-grid-2">
            <div className="info-card">
              <div className="info-card-num">Check 1</div>
              <h3>The facility’s own record mentions the service</h3>
              <p className="muted small">
                The service has to appear in the facility’s own <code>procedure</code>, <code>equipment</code>,{' '}
                <code>capability</code> or <code>description</code> fields. A broad specialty on its own isn’t enough.
              </p>
            </div>
            <div className="info-card">
              <div className="info-card-num">Check 2</div>
              <h3>Text about other hospitals doesn’t count</h3>
              <p className="muted small">
                Web snippets that describe a different hospital, or read like a directory listing, are flagged and
                left out, so a merged record can’t mislead anyone.
              </p>
            </div>
            <div className="info-card">
              <div className="info-card-num">Check 3</div>
              <h3>The record is trustworthy (trust ≥ 0.50)</h3>
              <p className="muted small">
                A record loses trust when its coordinates disagree with its India Post PIN location, when it rests on
                one thin web source, or when its fields look shifted or corrupted.
              </p>
            </div>
            <div className="info-card">
              <div className="info-card-num">Checks 4 and 5</div>
              <h3>The right kind of facility, within reach</h3>
              <p className="muted small">
                An eye clinic or dental practice can’t pass for NICU or dialysis. Each service also has its own
                travel distance: <code>τ × 3</code> for routine care, <code>τ × 2</code> in an emergency.
              </p>
            </div>
          </div>
        </section>

        <section className="info-section">
          <h2>2 · Scoring and the three picks</h2>
          <div className="formula-banner">
            <code>score = w₁·proximity + w₂·evidence + w₃·trust + w₄·depth</code>
            <span className="muted small">where proximity = exp(−km / τ) and evidence = evidence_score × type_fit</span>
          </div>
          <div className="info-grid-3">
            <div className="info-card">
              <span className="tier-label">Pick 1</span>
              <h3>Best balanced</h3>
              <p className="muted small">
                The highest combined score for distance, evidence, record trust and capacity (beds, doctors and named
                units).
              </p>
            </div>
            <div className="info-card">
              <span className="tier-label">Pick 2</span>
              <h3>Nearest that passes</h3>
              <p className="muted small">
                The closest facility that passes all five checks, preferring Medium or High confidence. Useful when
                travel time is the biggest risk.
              </p>
            </div>
            <div className="info-card">
              <span className="tier-label">Pick 3</span>
              <h3>Most confident</h3>
              <p className="muted small">
                The strongest evidence and record trust within the search area, even if it’s further away.
              </p>
            </div>
          </div>
        </section>

        <section className="info-section">
          <h2>3 · Confidence levels and care deserts</h2>
          <div className="rubric-table">
            <div className="rubric-row">
              <span className="chip chip-high">High</span>
              <span>
                Two or more separate fields mention the service (<code>evidence ≥ 0.75</code>), trust is at least
                0.75, and the facility type fits.
              </span>
            </div>
            <div className="rubric-row">
              <span className="chip chip-medium">Medium</span>
              <span>
                The record mentions the service directly (<code>evidence ≥ 0.50</code>), usually in one field, and
                trust is at least 0.50. Call to confirm.
              </span>
            </div>
            <div className="rubric-row">
              <span className="chip chip-low">Low</span>
              <span>
                Little evidence, or something looks off. Shown only when nothing stronger is available, and always
                with a note to call first.
              </span>
            </div>
          </div>
          <p className="muted small mt-3">
            If no facility passes within a service’s safe travel distance (<code>τ</code>), care.in shows a care
            desert alert. It draws that distance on the map, searches up to 600 km for the nearest option, and
            suggests also calling the district public hospital.
          </p>
        </section>

        <div className="info-cta">
          <button type="button" className="btn btn-primary" onClick={onStartSearch}>
            <span>Start a search</span>
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
          <span className="kicker">About care.in</span>
          <h1>Helping people in India find the right care</h1>
          <p className="muted">
            care.in is for ASHA workers, NGO coordinators, clinicians and families who need to know where a
            patient can get a specific kind of care, and how far to trust that answer.
          </p>
        </header>

        <section className="info-section">
          <div className="info-grid-3">
            <div className="info-card">
              <span className="info-icon"><IconDatabase size={20} /></span>
              <h3>The data</h3>
              <p className="muted small">
                Built from {rawRecords} Virtue Foundation facility records ({uniqueRecords} after removing duplicates,{' '}
                {usableRecords} with a usable location), checked against 165,627 India Post PIN locations and NFHS-5
                health indicators for 706 districts.
              </p>
            </div>
            <div className="info-card">
              <span className="info-icon"><IconMic size={20} /></span>
              <h3>Voice and phone</h3>
              <p className="muted small">
                Callers can speak English, Hindi, Marathi, Bengali, Tamil, Telugu and other Indian languages. That
                helps where reading is hard or mobile data is slow.
              </p>
            </div>
            <div className="info-card">
              <span className="info-icon"><IconSliders size={20} /></span>
              <h3>The reasons, shown</h3>
              <p className="muted small">
                Each result quotes the facility’s own record and links its web sources. It flags location conflicts,
                lists closer facilities we skipped and why, and lets you change the ranking weights.
              </p>
            </div>
          </div>
        </section>

        <section className="info-section">
          <h2>How we decided</h2>
          <p className="muted">
            Every search starts from all {rawRecords} records and narrows them down in the same order:
          </p>
          <div className="info-card">
            <ol className="plain-list">
              <li>
                Remove exact duplicates ({uniqueRecords} left), then keep the records with a usable location (
                {usableRecords}).
              </li>
              <li>Keep the ones that mention the service anywhere, including a related specialty.</li>
              <li>Keep the ones within the service’s travel distance of the patient.</li>
              <li>Keep the ones whose own text mentions the service directly, not just a specialty.</li>
              <li>Keep the ones with a trustworthy record (trust ≥ 0.50) and the right type of facility.</li>
              <li>Score the rest on distance, evidence, record trust and capacity, and show the top picks.</li>
            </ol>
          </div>
          <p className="muted small mt-3">
            How sure we are (High, Medium or Low) depends on how many parts of the record mention the service and
            how much we trust the record. Low always comes with a note to call first. The full rules are on{' '}
            <em>How it works</em>.
          </p>
        </section>

        <section className="info-section">
          <h2>How it’s built</h2>
          <div className="info-card">
            <ul className="plain-list">
              <li>
                The data pipeline runs on Databricks with Unity Catalog. Bronze, silver and gold Delta tables fix
                state spellings, catch merged or corrupted records, pull out the evidence for each service, and export
                Parquet files for serving.
              </li>
              <li>
                Search runs on FastAPI and DuckDB inside one Databricks App. The checks and scoring are plain code, and
                a search takes under 50 ms.
              </li>
              <li>
                Voice uses LiveKit and Gemini Live. The agent can only answer from care.in’s own tools, and{' '}
                <code>/monitor</code> shows each call’s search as it happens.
              </li>
            </ul>
          </div>
        </section>

        <div className="info-cta">
          <button type="button" className="btn btn-primary" onClick={onStartSearch}>
            <span>Start a search</span>
            <IconArrowRight size={16} />
          </button>
        </div>
      </article>
    )
  }

  // Policy
  return (
    <article className="info-page">
      <header className="info-hero">
        <span className="kicker">Policy</span>
        <h1>Disclaimer, data limits and privacy</h1>
        <p className="muted">Effective November 2026</p>
      </header>

      <section className="info-section">
        <div className="notice notice-warn">
          <IconAlert size={18} />
          <span>
            <strong>Not medical advice.</strong> care.in helps you find facilities and shows what their records
            say. It doesn’t diagnose, can’t promise a free bed or working equipment today, and doesn’t replace a
            clinician’s judgement. In a life-threatening emergency in India, call <strong>108</strong>.
          </span>
        </div>
      </section>

      <section className="info-section info-prose">
        <div className="info-card">
          <div className="policy-head">
            <IconShieldCheck size={18} />
            <h3>1. Where answers come from</h3>
          </div>
          <p className="muted small">
            The website and the voice assistant only show facilities returned by care.in’s search engine. Neither
            may make up hospital names, phone numbers, bed counts, services or distances. Each claim shows the field
            it came from and a confidence level.
          </p>
        </div>

        <div className="info-card">
          <h3>2. What the data covers</h3>
          <p className="muted small">
            Most records come from the Virtue Foundation’s web-extracted dataset and public Indian directories.
            Government facilities (PHCs, CHCs and district hospitals) are often missing online, so a care desert alert
            means there’s no record we trust <em>in this dataset</em>, not that there’s no public care nearby. Always
            call to check equipment, specialists and insurance (for example PM-JAY / Ayushman Bharat) before
            travelling.
          </p>
        </div>

        <div className="info-card">
          <h3>3. Privacy</h3>
          <p className="muted small">
            A search needs only the type of care and a rough location (PIN code, town or GPS). We don’t ask for or
            store names, Aadhaar numbers or health records. Browser voice sessions use LiveKit room tokens that expire
            after 15 minutes. Please don’t share personal medical details during a call.
          </p>
        </div>

        <div className="info-card">
          <h3>4. Corrections</h3>
          <p className="muted small">
            Hospital administrators, NGOs and district planners can send corrections to coordinates, phone numbers or
            services through the Virtue Foundation’s open-data channel or the partner Databricks feed.
          </p>
        </div>
      </section>

      <div className="info-cta">
        <button type="button" className="btn btn-primary" onClick={onStartSearch}>
          <span>Back to search</span>
          <IconArrowRight size={16} />
        </button>
      </div>
    </article>
  )
}
