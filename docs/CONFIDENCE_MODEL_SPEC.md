# Spec: a learned confidence score for Care Finder

Owner: Mekeli (pipeline), Bryce (audit). Status: building, Nov 21 2026. Deadline Nov 22, 12:30 PM.

## Why

Care Finder rates every facility × service claim High, Medium or Low with hand-written rules
(`gold/21` evidence, `gold/22` trust, `gold/23` confidence). The first AI review of 200 claims
(`hc_gold.llm_review_changes`) showed the rules are too generous:

| Rule rating | Reviewed | Kept | Downgraded | Excluded (planned, referral, not available) | Upgraded |
|---|---|---|---|---|---|
| High | 151 | 89 (59%) | 57 | 5 | 0 |
| Medium | 43 | 4 | 12 | 18 | 9 |

We want a confidence score that is **learned from labelled examples and measured**, so "High" means a
known hit rate. It also answers the judging criterion "advanced models, meaningful relationships".

**What does not change:** ranking still runs on cited evidence, distance and trust. The model only
changes how sure we *say* we are, and which claims get checked next. The voice agent stays template-only.

## Scope

In: labels (LLM batch), training table, LightGBM + SHAP via `gold/30`, head-to-head with the rules,
calibration, new band cut-offs, scores for all 40,129 pairs, SHAP reasons in gold.
Out (later): changing the app's bands and spoken wording (step 5b, after the team looks at the numbers).

## How we use Databricks' LLM features

| Feature | What we use it for |
|---|---|
| **Foundation Model APIs** (pay-per-token endpoints on the Serving page) | `databricks-meta-llama-3-3-70b-instruct`, the same model as the first 200 labels. No endpoint to deploy. |
| **`ai_query()`** (SQL AI Function) | Runs the prompt over a whole table in one SQL statement. Databricks parallelises the calls on serverless compute. |
| `responseFormat => '<JSON schema>'` | Forces a fixed answer shape: verdict, confidence, quotes, requirements found / missing, red flags. |
| `failOnError => false` | A bad row returns an error message instead of failing the batch; we keep it per row. |
| `modelParameters => named_struct('temperature', 0.0, ...)` | Same answer for the same input, so labels are reproducible. |
| **MLflow** (experiment + Unity Catalog registry) | Every training run, metric, SHAP plot and the model itself. |

Free Edition has fair-use limits on model calls. Batches are 200 rows and the loop resumes where it
stopped, so a limit or timeout costs a re-run, not the work done.

## Step 1 · A fair label set (`gold/32_llm_labels.py`)

**Sample.** From `hc_gold.care_finder_index` (one row per facility × service), stratify by
service (16) × rule confidence (High / Medium / Low) = 48 cells and draw **25 per cell at random**
(≈1,200 pairs). Every cell has at least 33 pairs, so all cells fill. The draw is deterministic
(hash of ids + seed) and stored in `hc_gold.llm_label_sample`, so re-runs send the same rows.
Pairs already reviewed or in the hand audit are not drawn twice.

Each row keeps `pop_n` (pairs in its cell) and `sample_weight = pop_n / n_drawn`. Stratifying on the
rule rating does not bias what the model learns (P(offered | inputs)), because the rating is itself a
function of the inputs. The weights are only needed for **population** numbers, e.g. "what share of all
High claims hold up".

**Also labelled:** the 43 hand-audit pairs that have no LLM answer yet, so we can measure LLM vs human.

**Prompt and model.** Identical to `02_llm_review` (the first 200): same instructions, guideline
requirements (`hc_gold.guideline_rules`), record text, JSON schema, model and temperature.

**Grounding.** Every quote the model gives must appear in the record (after lower-casing and removing
punctuation). An "available" answer with no verified quote becomes "unclear".

**Verdict → label**

| Verdict | Label |
|---|---|
| available (with a verified quote) | 1 |
| not_available, planned, referral_only | 0 |
| unclear, parse error | NULL: left out of training, counted separately |

**Roles** (`origin` column in `hc_gold.llm_labels`)

| Role | Rows | Used for |
|---|---|---|
| `random` | ≈1,200 | training and out-of-fold evaluation |
| `priority_negation` | 81 (first review) | stress test: claims worded "planned", "coming soon", "refer". Never trained on. |
| `priority_high_acuity` | 119 (first review) | extra holdout, reported separately (picked by priority, not at random) |
| `audit` | 43 | final exam against people. Never trained on. |

## Step 2 · Training table (`gold/33_confidence_features.py`)

`hc_gold.confidence_features`: one row per pair, all 40,129. `hc_gold.confidence_training`: the
`random` rows with a label, plus `label`, `facility_id`, `service_key`.

| Group | Inputs |
|---|---|
| Evidence | fields mentioning the service, direct fields, snippets, direct snippets, has specifics, direct tier, only third-party text, evidence text length, name kind, name conflict |
| Wording | negation / future / referral words in the evidence ("not available", "planned", "coming soon", "refer") |
| Record trust | every `flag_*` from `facility_trust`, number of web sources |
| Outside sources | listed in the national directory, directory ownership |
| Size and type | facility type, ownership, beds, doctors, year established |
| Survey prior | IHDS share of similar facilities (type × ownership) offering this service (7 services have a survey proxy; others NULL) |
| Service | service key, high-acuity flag |

**Left out on purpose:** our own scores (`evidence_score`, `confidence`, `base_score`, `type_fit`,
`trust_score`), so the comparison with the rules is fair; and anything from the LLM's answer, which is
where the label comes from.

## Step 3 · Train (`gold/30_model_template.py`, job `hc_confidence_model`)

`source_table = confidence_training`, `target_col = label`, `group_col = facility_id`,
`id_cols = facility_id`. Grouping keeps all of one hospital's services on one side of every split.
`gold/30` trains dummy, logistic and LightGBM, logs to MLflow, and writes `model_leaderboard`,
`model_feature_importance` and `pred_confidence_training__label`.

## Step 4 · Measure against the rules (`gold/34_confidence_model.py`)

A small LightGBM (8 leaves, at least 25 rows per leaf) is trained out-of-fold, grouped by facility.

| Test | Pass looks like |
|---|---|
| AUC of the rule score vs the model, same out-of-fold rows | model clearly higher; if not, we say so |
| Calibration (10 bins, predicted vs observed) | points near the diagonal; isotonic calibration if not |
| Precision of "High" (weighted to the population) | rules ≈ 59% today; model cut-off chosen so High ≥ 85% |
| 81 negation rows | most fall below the Medium cut-off; compare with how many the rules rated High |
| 43-row hand audit (once filled) | accuracy of rules, model and LLM against people; LLM-human agreement |

## Step 5 · Use it

**5a (this build).** Score all 40,129 pairs into `hc_gold.service_confidence_model`: `p_offered`
(calibrated), `model_band` (from the measured cut-offs), the rule confidence next to it,
`disagreement` (rules High, model Low or the reverse), and the top reasons (two pushing up, one pushing
down). Disagreements are the next review queue.

**5b (after review).** Swap the app's band cut-offs for the measured ones, and map SHAP reasons to fixed
phrases in `backend/app/summary.py` (e.g. direct mentions → "they mention it in three places";
in directory → "they're in the government hospital list"; small clinic → "it's a small clinic, so call
first").

## Step 6 · What the judges see

1. Leaderboard: dummy vs logistic vs LightGBM.
2. Rules vs learned score: AUC, and precision of High.
3. Calibration plot.
4. SHAP summary: what makes a claim believable.
5. Honesty line: "Labels are from Llama 3.3 70B, checked against N human audits with X% agreement."

## Risks

| Risk | Mitigation |
|---|---|
| The model learns to copy the LLM | Human audit is the final exam; we report LLM-human agreement |
| ≈1,000 labels is small | Small trees, grouped CV, logistic as a check, no claims beyond the numbers |
| "Unclear" is common (15% in the first 200) | Counted and reported; not forced into 0 or 1 |
| Record text changed slightly since the first 200 (cleaning fixes) | Same prompt and model; noted in the report |
| Free Edition rate limits | 200-row resumable batches |

## Run

```
databricks bundle deploy -t free --profile Mekeli
databricks bundle run hc_confidence_model -t free --profile Mekeli
```

Tasks: `llm_labels` → `features` → `train` (gold/30) and `score` (gold/34).

## Hand audit (Mekeli + Bryce)

Open `hc_gold.audit_sample`, hide `confidence`, `adjusted_confidence` and `llm_verdict`, then for each
row call or check the website and fill `audit_answer` with `yes_24x7`, `yes_limited`, `no` or
`no_answer`, plus `audit_notes` (say whether you called or used the website) and `checked_by`.
`gold/34` picks the answers up on its next run.
