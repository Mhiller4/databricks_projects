# The challenge: find the right care

CMU Datathon, Fall 2026 · dataset from the **Virtue Foundation** (a nonprofit that works with the
United Nations to improve access to healthcare in underserved regions).

> A patient needs a specific kind of care. Where should they go, and why should they trust that answer?

## Who asks this question

- A community health worker in rural Bihar has a patient who needs **dialysis**.
- An NGO coordinator in Maharashtra needs a hospital that can handle a **high-risk delivery**.
- A district planner needs to know where to send **trauma** cases from a highway accident hotspot.

They are all asking: *where is the best place to get this service, from here?*

## What we build

**Input:**
- **A service:** dialysis, emergency C-section, NICU, cardiac surgery, MRI, burn care, and so on.
- **A location:** a city, district, PIN code, or coordinates.

**Output:** the best facility option(s), each with a clear, evidence-based explanation of why it was chosen.

**Format:** our choice: an app, a dashboard, a Genie space, a notebook, an agent, or a mix. It must suit
the people who will use it, who are not technical.

## The one rule: show your reasoning

For **every** recommendation we must be able to answer:

| Question | What it means |
|---|---|
| **WHY this facility?** | What evidence says it exists, offers this service, and is the best choice for this location? |
| **HOW did we decide?** | What logic, scoring, model or rules turned about 10,000 records into this answer? What did we weigh, and what did we trade off? |

If the build can't explain itself, it doesn't meet the requirements, however good it looks.

## Submission requirements

- [ ] Runs on **Databricks Free Edition**
- [ ] Uses the **provided facility dataset**
- [ ] Supports a clear **non-technical user workflow**
- [ ] **Cites the underlying facility text** for every important claim, recommendation, score or ranking
- [ ] **Communicates uncertainty** instead of presenting weak evidence as fact
- [ ] Code, analysis, and video; due **Sun Nov 22, 12:30 PM**

## Judging criteria

| Criterion | What it rewards |
|---|---|
| Exploration | Novel datasets, insightful analysis |
| Modeling | Advanced models, meaningful relationships |
| Impact | Actionable policies |

## The data

The data comes as a Delta Share named `databricks_virtue_foundation_dataset_dais_2026`, with schema
`virtue_foundation_dataset`. We copy it into our own schemas (see [README](../README.md)).

| Shared table | Rows | Ours (bronze → silver) | What it is |
|---|---|---|---|
| `facilities` | 10,088 | `vf_facilities` | Healthcare facilities across India, 51 attributes |
| `india_post_pincode_directory` | 165,627 | `vf_india_post_pincode_directory` | India Post offices: PIN → office, district, state, lat/long |
| `nfhs_5_district_health_indicators` | 706 | `vf_nfhs_5_district_health_indicators` | National Family Health Survey 5, district-level health indicators |

**What each facility record contains**
- **Identity and location:** name, state, city, postcode, latitude/longitude, `cluster_id`.
- **What it says it offers:** `specialties`, `capability`, `procedure`, `equipment`. These are JSON arrays of text extracted from web pages.
- **Scale and history:** `numberDoctors`, `capacity` (beds), `yearEstablished`.
- **Evidence:** free-text `description`, and `source_urls` for the pages the record was built from.

**Coverage, as published:** description 100% · capability 99.7% · procedure 92.5% · equipment 77.0% ·
year established 47.8% · number of doctors 36.4% · capacity 25.2%.

Most fields were extracted from unstructured web text, so treat every field as a **claim to verify,
not ground truth**. Some records merge more than one facility, or have contradictory locations or
capabilities.

## What we've found so far (Sat Nov 21)

| Finding | Number |
|---|---|
| Exact duplicate rows | 11 (removed in silver; 10,077 remain) |
| Distinct `cluster_id` values | 9,959 for 10,077 rows: some clusters hold more than one record |
| Distinct facility names | 9,530: repeated names (chains, or the same place listed twice) |
| Distinct values in the state field | 253. India has 36 states and UTs, so there are spelling variants ("Tamilnadu") and cities in the state field ("Thane") |
| No coordinates | 118 |
| Coordinates outside India's bounding box | 6 |
| PIN codes not in the India Post directory | 205 of 9,909 |
| PIN code in a different state from the address (rough check) | about 420 |
| Rows with shifted columns (`unique_id` isn't a UUID, or a type field holds a hash) | about 88 |
| Records mentioning dialysis | 1,049 |
| Records mentioning NICU / neonatal intensive care | 709 |

A worked example of a merged record. "Aravind Eye Hospital" (an eye hospital) has city Hyderabad, a
Delhi PIN (110002), coordinates in Puducherry, 650 beds, 1 doctor, and a dialysis unit described in
`procedure`. That dialysis text comes from a different hospital's page. A keyword search for
"dialysis" would recommend an eye hospital.
