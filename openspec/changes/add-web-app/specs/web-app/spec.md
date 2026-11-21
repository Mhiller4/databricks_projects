# Web app

## ADDED Requirements

### Requirement: Voice session in the browser
The page SHALL let a user start a voice conversation with the Care Finder agent by tapping one button,
after choosing a role (health worker or patient / family). The role SHALL be passed to the agent so the
"press 1 / 2" step is skipped.

#### Scenario: Patient starts a voice session
- **WHEN** a user taps "Patient / family" and then the mic, and allows microphone access
- **THEN** the page connects to a new LiveKit room within 5 seconds, the agent greets them and first asks whether it's an emergency, and live captions appear

#### Scenario: Microphone blocked
- **WHEN** the browser denies microphone access
- **THEN** the page says so in plain words and points the user to the chat box and the search bar, which still work

### Requirement: Chat in the same conversation
The page SHALL offer a text box that sends typed messages into the same agent session. Typed and spoken
turns SHALL appear in one transcript.

#### Scenario: Typed follow-up
- **WHEN** during a voice session the user types "why not the closer one?"
- **THEN** the agent replies (spoken and in the transcript) using only the skipped-nearby reasons from its last search

### Requirement: Manual search without voice
The page SHALL provide a service selector, a location box and an urgency toggle that call
`POST /api/recommend` directly, without LiveKit.

#### Scenario: Voice services down
- **WHEN** LiveKit or Gemini is unreachable
- **THEN** manual search still returns and renders results, and the agent panel shows "Voice unavailable, use search"

### Requirement: Precise location input
The location box SHALL support type-ahead over PIN codes, localities, towns and districts, a
"use my location" (GPS) button, and a draggable map pin. It SHALL show how precise the chosen point is.

#### Scenario: Locality type-ahead
- **WHEN** the user types "Band"
- **THEN** suggestions include "Bandra West, Mumbai Suburban, Maharashtra" with district and state shown

#### Scenario: Rough location
- **WHEN** the user picks "Mumbai"
- **THEN** an amber badge says the point is the city centre and suggests adding an area or PIN code

#### Scenario: Adjust with the pin
- **WHEN** the user drags the you-pin to a new spot
- **THEN** the search reruns from those coordinates and the badge shows "exact point"

### Requirement: Results with evidence
Results SHALL show the map, up to three tiered cards (Best balanced, Nearest verified, Highest-confidence
specialist), and the funnel counts. Each card SHALL show distance, confidence as a word, at least one quoted
claim with its source field, the cautions, and a call button. The UI SHALL NOT show any facility that isn't
in the current API payload.

#### Scenario: Normal result
- **WHEN** a search for dialysis near "Darbhanga, Bihar" returns
- **THEN** three cards and three numbered green pins appear, and the funnel shows every stage from 10,088 down to 3

#### Scenario: Voice result reaches the page
- **WHEN** the agent runs a search during a web voice session
- **THEN** the same map, cards and funnel update from the `care-finder.result` message, without a page reload

### Requirement: Why & How drawer
Each card SHALL open a drawer with the quoted evidence and source links, the score breakdown by component
and weight, the confidence reason, the gates, closer facilities that were skipped and why, weight sliders
and a referral card.

#### Scenario: Sliders cannot surface unverified facilities
- **WHEN** the user sets proximity to the maximum and the other weights to zero
- **THEN** the ranking changes, and every card still has direct evidence (the API applies gates before weights)

#### Scenario: Referral card
- **WHEN** the user clicks "Copy referral"
- **THEN** a plain-text referral built only from payload fields (name, address, phone, why, confidence, cautions) is copied

### Requirement: Care-desert and clarification states
The page SHALL show a clear banner when no verified facility is within the safe distance, and SHALL ask
the user to choose when a place name is ambiguous.

#### Scenario: Desert
- **WHEN** a search for emergency c-section near Nanded returns no recommendations nearby
- **THEN** a red banner states that nothing verified is within 25 km in this dataset, the map shows the 25 km ring, and the nearest verified option (about 100 km) is shown as a card

#### Scenario: Ambiguous place
- **WHEN** the user searches "Aurangabad"
- **THEN** the page shows buttons for "Aurangabad, Maharashtra" and "Aurangabad, Bihar", and clicking one reruns the search

### Requirement: Monitor screen for phone calls
The app SHALL provide a `/monitor` page that shows the latest phone-call search live over `WS /ws/live`.

#### Scenario: Phone demo
- **WHEN** someone calls the phone number and the agent runs a search
- **THEN** `/monitor` shows that result (map, cards, funnel) within 2 seconds

### Requirement: Deployed and managed in Databricks
The web app, API and voice worker SHALL be deployed as a Databricks App defined in this bundle, with keys
in a Databricks secret scope and data read from the Unity Catalog volume. No other hosting service SHALL
be used.

#### Scenario: Fresh deploy
- **WHEN** a teammate runs `scripts/build_app.sh`, `databricks bundle deploy -t free` and `databricks bundle run care_finder -t free`
- **THEN** the app starts, loads the Parquet from `workspace.hc_gold.serving`, and the page works at the app URL

#### Scenario: Data refresh
- **WHEN** the `hc_care_finder` job reruns and the app is restarted
- **THEN** the app serves the new data with no code change

### Requirement: Usable by non-technical users on a phone
The page SHALL work at 360 px wide, use plain language, have tap targets of at least 44 px, never use colour
as the only signal, and support dark mode.

#### Scenario: Health worker on a phone
- **WHEN** a health worker opens the app on a low-end Android phone
- **THEN** they can run a search and read a result card without zooming or scrolling sideways
