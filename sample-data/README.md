# Synthetic lead dataset

`synthetic-leads.json` holds 60 fictional inquiries with ground-truth labels. It is the
evaluation set for normalization, extraction and scoring, and the input for scenario tests.

**Do not edit the JSON by hand.** Edit `build_synthetic_leads.py` and re-run it:

```bash
python3 sample-data/build_synthetic_leads.py
```

`tests/data/test_synthetic_leads.py` fails if the JSON and the generator disagree.

All names, phone numbers (`+2010000xxxxx`) and emails (`@example.com`) are fictional.

## Record shape

| Field | Meaning |
|---|---|
| `id`, `event_id` | Record id and webhook event id (the idempotency source). A redelivery reuses `event_id`. |
| `source` | `form` or `email` (WhatsApp is deferred). Some forms carry only a phone number. |
| `language` | `en`, `ar`, `arz-latn` (Arabizi) or `mixed`. Only `en` is supported for now (see below). |
| `tags` | Scenario categories (`injection`, `opt_out`, `duplicate_contact`, ...). |
| `duplicate_of` / `redelivery_of` | A new inquiry from a known contact, or an exact webhook redelivery. |
| `payload` | What the webhook receives (raw phone and email formats vary on purpose). |
| `expected.normalized` | E.164 phone and lowercased email. |
| `expected.extraction` | Ground-truth structured fields (below). |
| `expected.score` | Total, per-rule components and priority under the reference rules. |

## English only (for now)

`supported_languages` is `["en"]`. Non-English records keep full extraction labels so they are
ready when Arabic support is added, but today they are expected to go to **human review**
(`needs_human_review: true`, tag `unsupported_language`) instead of being extracted.

**Evaluate extraction and scoring on `language == "en"` records only.** For the others, the
check is simply that they were routed to review. An opt-out in an unsupported language must
still stop all sends.

## Labeling conventions

- **Budget:** "6-8 million" gives `budget_min=6000000`, `budget_max=8000000`. A single figure or "up to X" gives only `budget_max`. Currency defaults to `EGP` when a budget exists.
- **Location:** canonical names (`New Cairo`; "Fifth Settlement" and "Tagamoa" map to it). Neighbourhoods roll up to the city (Smouha gives `Alexandria`).
- **Bedrooms:** a studio is `0`. `null` for land, commercial and office, and when not stated.
- **Timeline:** whole months, rounded up (6 weeks gives 2). Relative dates that depend on today's date ("before September") are not labeled and are listed in `skip_fields`.
- **Intent:** `high` only for an explicit, near-term commitment ("ready to book", "urgent", "deciding this week"). `low` for explicit browsing or no hurry. `unknown` when there is no signal.
- **`skip_fields`:** fields that are genuinely ambiguous. The evaluation harness must not count them.
- **`needs_human_review`:** true for injection attempts, conflicting or invalid requirements, requests for a person, and out-of-scope requests (rentals), and unsupported languages.

## Reference scoring (version `reference-1`)

Computed at intake, so the follow-up reply component is always 0 here.

| Rule | Points | Condition |
|---|---|---|
| `budget_provided` | 20 | `budget_min` or `budget_max` present |
| `timeline_within_3_months` | 30 | timeline of 3 months or less |
| `requirements_complete` | 20 | property type and location present, and bedrooms present (not needed for land, commercial, office) |
| `explicit_high_intent` | 20 | intent is `high` |
| `followup_response` | 10 | customer replied to a follow-up (not applicable at intake) |

Priority: 80 and above is `high`, 50 to 79 is `standard`, below 50 is `nurture`. The intake maximum is therefore 90.

These rules are configurable examples from the project description, not validated benchmarks.

## Not yet labeled

Property-match outcomes. Records tagged `no_match` are *intended* to find nothing. Confirm that
against the catalog once it exists (task 2.7).
