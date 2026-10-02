# Evaluation report: AI lead qualification

Measured on 2026-10-02. All data is synthetic. Raw reports are in `docs/eval/`.

## Summary

With `openai/gpt-oss-120b` on Groq and prompt `qualify-v2`, field-level extraction accuracy on
the 50 English records was **98.2% and 99.3% in two runs** (436 and 441 of 444 fields).
Every field except purchase intent was extracted correctly in every run. Purchase intent, the
most subjective field, scored 42/50 and 47/50.

The safety-relevant decisions were stable across all runs: every case that needed a person
was handed off (review recall 100%), every opt-out and every prompt-injection attempt was
detected, and every non-English inquiry was routed to a salesperson. The only decision error
was one unnecessary handoff (precision 95%).

These numbers describe a small synthetic dataset written by the same person who wrote the
prompt. They show that the pipeline works as designed; they are not evidence of accuracy on
real customer messages.

## Conditions

| Item | Value |
|---|---|
| Model | `openai/gpt-oss-120b` via Groq, strict JSON-schema mode, temperature 0, default reasoning effort |
| Dataset | `sample-data/synthetic-leads.json`: 60 records, 50 English (field accuracy) and 10 non-English (routing only) |
| Fields | 9 per English record, minus each record's ambiguous `skip_fields`: 444 field comparisons |
| Matching | Exact match after the deterministic post-processing (location canonicalisation, studio = 0 bedrooms, single budget figure = maximum) |
| Pacing | 2.5 to 3 s between records (Groq free tier); 429 responses retried with Retry-After |
| Harness | `make eval` (`app/evaluate.py`) |

## Results

| Run | Prompt | Dataset | Field accuracy | Purchase intent | Review precision / recall | Opt-out | Injection | Non-English routed | Median latency |
|---|---|---|---|---|---|---|---|---|---|
| 1 (baseline) | v1 | 1.0 | 427/444 (96.2%) | 42/50 | 0.91 / 1.00 | 3/3 | 4/4 | 10/10 | 2.5 s |
| 2 | v2 | 1.1 | 436/444 (98.2%) | 42/50 | 0.95 / 1.00 | 3/3 | 4/4 | 10/10 | 2.4 s |
| 3 | v2 | 1.2 | 441/444 (99.3%) | 47/50 | 0.95 / 1.00 | 3/3 | 4/4 | 10/10 | 1.7 s |

Latency includes waits caused by the free tier's rate limits; the 90th percentile ranged from
3.6 s to 11.9 s depending on how often requests were throttled.

### What changed between runs

- **Run 1 to run 2 (prompt v1 to v2, dataset 1.0 to 1.1).** The baseline errors fell into four
  groups. Two were model errors fixed in the prompt and in code: a single budget figure was put
  in both `budget_min` and `budget_max` (now also normalised deterministically), and "ready to
  buy/sign" was read as wanting a ready-to-move-in property. One group was a labelling error:
  three records were labelled `apartment` for messages that never state a type, contradicting
  the documented convention and another record (L060); the model followed the convention. The
  fourth group was purchase intent, where the rules were made more precise in both the prompt
  and the labelling guide, and two labels that contradicted the existing rules were corrected.
- **Run 2 to run 3 (dataset 1.1 to 1.2, same prompt).** One more label with the same kind of
  error (L044) was corrected. That accounts for one of the five extra correct intent fields;
  the other four reflect run-to-run variation (below).
- Run 1 was scored against dataset 1.0, so it is not directly comparable with the later runs.
  All label changes are listed in `sample-data/README.md` (changelog), with the rule that no
  label was changed to match a model output the written conventions do not support.

### Run-to-run variation

Runs 2 and 3 used the same prompt and, apart from one label, the same data, yet purchase
intent varied by several records between runs. The model is not fully deterministic even at
temperature 0. Single-run figures for this field should therefore be read as a range, not a
point estimate. The other eight fields did not vary. Two runs are a thin basis for a
variability estimate; a third run was attempted but aborted (free-tier pacing made it slow and
it was stopped by mistake), and adding more runs is the obvious next step.

### Remaining errors (final runs)

- **Purchase intent** (3 to 8 records per run): mostly "requests a person" rated `low` instead
  of `medium`, and "ready to move in" read as a commitment to buy (`high`) rather than a
  delivery preference. Impact: purchase intent is worth 20 of 100 score points, so an error can
  move a lead between priority bands. It cannot cause an unsafe action: priority only changes
  ordering and whether the rep gets a high-priority email.
- **One unnecessary handoff** in every v2 run: "Can you call me tomorrow?" (L058) was treated
  as asking for a person. This is defensible and errs on the safe side: a salesperson contacts
  the customer.

## Limitations

- **Small, synthetic, self-labelled data.** 50 English records written and labelled by the same
  author as the prompt. Labels were corrected after the first run (documented). A held-out set
  written by someone else is needed before any claim about real-world accuracy.
- **English only.** The 10 non-English records only test routing to a salesperson.
- **Free-tier throttling** affects latency figures, not accuracy. At 8,000 tokens per minute only
  about two qualifications per minute fit, so a full run takes 20-30 minutes.
- **No measurement of real conversion or revenue.** Nothing here supports such claims.

## Reproduce

```bash
# .env: LLM_PROVIDER=groq, GROQ_API_KEY=..., GROQ_MODEL=openai/gpt-oss-120b
docker compose up -d ai-service
make eval            # writes docs/eval/<model>-<date>.json and docs/eval/latest.json
```
