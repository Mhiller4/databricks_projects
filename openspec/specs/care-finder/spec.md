# Care Finder

## Purpose

Given a medical service and a location in India, recommend the facilities most likely to actually
provide that service near that location. Every recommendation is justified with cited facility text,
and every recommendation says how certain it is.
Background and data: [docs/CHALLENGE.md](../../../docs/CHALLENGE.md).

Status: **draft**, written at kickoff on Sat Nov 21. The approach notes at the end are proposals for the team to confirm.

## Requirements

### Requirement: Service input
The system SHALL accept a service as either a choice from a fixed list or free text. It SHALL map that
input to a canonical service with a known set of evidence terms.

#### Scenario: Picked from the list
- **WHEN** the user selects "Dialysis"
- **THEN** the search uses the canonical service `dialysis` and its terms (e.g. dialysis, haemodialysis, nephrology, dialysis machine)

#### Scenario: Free text
- **WHEN** the user types "kidney machine"
- **THEN** the system maps it to `dialysis` and shows the user which service it chose

#### Scenario: Unknown service
- **WHEN** the input matches no canonical service
- **THEN** the system says so, offers the closest services, and does not return a ranking

### Requirement: Location input
The system SHALL accept a city, district, PIN code, or latitude/longitude. It SHALL resolve each of
these to a point, using the India Post PIN directory for PINs, districts and cities.

#### Scenario: PIN code
- **WHEN** the user enters PIN 800001
- **THEN** the location resolves to that PIN's post-office coordinates, and the resolved place name is shown

#### Scenario: Ambiguous place name
- **WHEN** a city or district name matches places in more than one state
- **THEN** the system asks the user to pick the state before ranking

#### Scenario: Unresolvable location
- **WHEN** the location can't be resolved
- **THEN** the system says so and returns no ranking

### Requirement: Ranked recommendations
The system SHALL return a short ranked list of facilities (3 to 5 by default) for the service and
location. It SHALL order the list by a documented score that combines strength of evidence for the
service, distance, and trust in the record.

#### Scenario: Normal result
- **WHEN** a user searches for dialysis near a resolved location
- **THEN** each result shows the facility name, address, distance, score, confidence level, and the evidence behind it

#### Scenario: Nothing nearby
- **WHEN** no facility with credible evidence is within the default radius
- **THEN** the system says so plainly, then shows the nearest credible options with their distances

### Requirement: Cited evidence (WHY)
Every recommendation SHALL cite the facility text that supports it. A citation is the source field
name plus the quoted text, and the record's source URLs SHALL be shown.

#### Scenario: Evidence shown
- **WHEN** a facility is recommended for dialysis
- **THEN** the result quotes the matching text (e.g. `procedure: "20-bed Dialysis Unit with 10 machines"`) and lists its source URLs

#### Scenario: No direct evidence
- **WHEN** a facility qualifies only through indirect evidence (e.g. a nephrology specialty with no dialysis procedure or equipment)
- **THEN** it is labelled as indirect evidence and ranks below facilities with direct evidence

### Requirement: Uncertainty
Each recommendation SHALL show a confidence level (High, Medium or Low) and the reasons for it.
Weak or conflicting evidence SHALL NOT be presented as fact.

#### Scenario: Conflicting record
- **WHEN** a record's PIN code, coordinates and state disagree, or its text looks merged from more than one facility
- **THEN** its confidence is lowered and the conflict is stated (e.g. "PIN is in Delhi but coordinates are in Puducherry")

#### Scenario: Sparse record
- **WHEN** a record has a single source and no capacity, doctor count or equipment
- **THEN** its confidence is Low, and the result says what is missing

### Requirement: Explainable method (HOW)
The scoring method SHALL be documented in the product itself, in plain language, including the weights
and trade-offs. Each result SHALL show how its score breaks down into components.

#### Scenario: User asks why one facility ranks above another
- **WHEN** the user opens the details for a result
- **THEN** they see each score component (evidence, distance, trust) and its contribution

### Requirement: Non-technical workflow
The primary interface SHALL be usable by a community health worker with no data training: two inputs,
one action, and plain-language results.

#### Scenario: First use
- **WHEN** a new user opens the tool
- **THEN** they can get a recommendation without reading instructions or writing SQL

### Requirement: Runs on Free Edition
The full pipeline and the interface SHALL run on Databricks Free Edition using serverless compute,
within the Free Edition app and warehouse limits.

## Proposed approach (to confirm)

1. **Bronze:** copy the shared tables unchanged. **Done.**
2. **Silver:** clean the tables; flag shifted-column rows; standardize states; validate PIN, coordinates and state against the India Post directory. **Done:** `hc_silver.facility_master`. When the coordinates and the PIN disagree by more than 50 km, the listed city breaks the tie.
3. **Gold `facility_service_evidence`:** **done**. One row per facility × canonical service. Each row holds:
   - the matched text snippets, each with its source field
   - an evidence tier: direct procedure or equipment > capability > specialty only > description only
   - corroboration: how many fields and sources agree
4. **Gold `facility_trust`:** **done**. Per-facility trust flags covering:
   - location conflicts
   - merged-record signals (several facility names inside one record, or a service that doesn't fit the facility type)
   - completeness
   - number of sources
5. **Scoring:** **done**, in `care_finder_index` + `recommend_facilities()` + `resolve_location()`. `score = evidence × type fit × trust × exp(−km / tau)`; the weights are in `src/hc/care.py` and `gold.service_catalog`.
   A model (e.g. one that predicts whether a claim is corroborated) could come later, if time allows.
6. **Interface:** voice agent built (`voice_agent/`, `backend/`); web app specified in [openspec/changes/add-web-app/](../../changes/add-web-app/proposal.md). A Databricks App for the health-worker workflow, possibly with a Genie space for planners'
   open questions. Optionally an LLM (`ai_query`) to map free-text services and write the explanation.
   Any explanation must quote only retrieved evidence.
