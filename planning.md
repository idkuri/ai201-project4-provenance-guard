# Provenance Guard Planning

## Detection Signals

Signal 1 is Groq (`llama-3.3-70b-versatile`). It reads the text and judges whether it feels like AI writing or a real person. Returns a float 0 to 1 (`llm_score`). Higher = more likely AI.

Why I picked it: it catches polished, generic AI prose that heuristics miss.

Blind spot: formal human writing (essays, academic stuff) can look "too clean" and get flagged.

Signal 2 is stylometric heuristics in pure Python. It measures:
- Sentence length variance (low variance = higher AI score)
- Type-token ratio / vocab diversity (low diversity = higher AI score)
- Punctuation density deviation from a typical human range

Returns a float 0 to 1 (`stylometric_score`). Higher = more uniform/AI-like.

Why I picked it: AI text tends to be structurally even. Humans are messier.

Blind spot: minimalist poetry with repetition tanks the type-token ratio even when a human wrote it.

How they combine:
```
confidence = 0.6 * llm_score + 0.4 * stylometric_score
```
60/40 because the LLM is better at meaning, stylometrics catch uniform structure.

Each signal outputs a 0-1 float, not a binary flag.

## Uncertainty Representation

A confidence of 0.6 means "60% chance this is AI." Not enough to call it definitively, so it lands in the uncertain band.

Both signals already output 0-1. Weighted average = final confidence.

Thresholds (I made the AI band harder to hit on purpose, false positives suck on a writing platform):

| Range | Attribution | Label |
|-------|-------------|-------|
| >= 0.80 | `likely_ai` | High-confidence AI |
| <= 0.30 | `likely_human` | High-confidence human |
| 0.30 to 0.80 | `uncertain` | Uncertain |

0.51 and 0.95 should produce different labels and different label text. That's the whole point.

## Transparency Labels

Exact text users see (`{pct}` is rounded percentage):

**High-confidence AI** (>= 0.80):
> "Likely AI-generated. Our analysis found strong signs of automated writing (confidence: {pct}%). This is a high-confidence call, not a guarantee."

**High-confidence human** (<= 0.30):
> "Likely human-written. Our analysis found strong signs of authentic, personal writing (confidence: {pct}%). This is a high-confidence call, not a guarantee."

**Uncertain** (0.30 to 0.80):
> "Attribution uncertain. We couldn't confidently tell if this is human or AI (confidence: {pct}%). Creators can appeal this result."

For AI/uncertain labels, `{pct}` = `round(confidence * 100)`. For human labels, `{pct}` = `round((1 - confidence) * 100)`.

## Appeals Workflow

Who: the original creator (`creator_id` must match the stored record).

They POST to `/appeal` with `content_id`, `creator_id`, and `creator_reasoning`.

When an appeal comes in:
1. Look up the submission. 404 if missing, 403 if wrong creator.
2. Flip status from `classified` to `under_review`.
3. Log the appeal reason and timestamp alongside the original decision.
4. Return a confirmation JSON.

No auto re-classification. A human reviewer handles it later.

What a reviewer sees in `GET /log`: original attribution, confidence, both signal scores, creator_id, appeal_reasoning, status `under_review`.

## Edge Cases

1. Formal academic human writing. Low sentence variance + big words can trick stylometrics. Should land in uncertain, not high-confidence AI.
2. Lightly edited AI output. Casual edits fool the LLM but stylometrics still see uniformity. Should land uncertain with appeal available.
3. Repetitive minimalist poetry. Short repeated lines kill type-token ratio. Stylometrics may false-positive; uncertain band helps but doesn't fix it completely.

## Architecture

```
[Client] --POST /submit {text, creator_id}--> [Flask-Limiter]
    |                                              |
    | (429 if exceeded)                            v
    |                                    [POST /submit]
    |                                              |
    |                         +--------------------+--------------------+
    |                         v                    v                    |
    |                  [Signal 1: Groq]    [Signal 2: Stylometrics]    |
    |                         |                    |                    |
    |                         +---------> [Confidence Scoring] <-------+
    |                                         |
    |                         +---------------+---------------+
    |                         v               v               v
    |                  [Label Generator] [SQLite Store] [Audit Log]
    |                         |                               |
    |                         v                               v
    |                  [JSON Response]                   [GET /log]

[Creator] --POST /appeal {content_id, creator_reasoning}--> [POST /appeal]
                                                                  |
                                    [SQLite: status -> under_review]
                                    [Audit Log: appeal + original decision]
```

Submission: text hits `/submit`, rate limiter checks it, both signals score it, scoring combines them, label generator picks the text, everything gets logged, JSON goes back.

Appeal: creator POSTs to `/appeal` with their reasoning, status flips to `under_review`, appeal gets logged next to the original call. Reviewer checks `GET /log`.

## API Contract

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/submit` | POST | `{ text, creator_id }` | `{ content_id, attribution, confidence, label }` |
| `/appeal` | POST | `{ content_id, creator_id, creator_reasoning }` | `{ message, content_id, status }` |
| `/log` | GET | none | `{ entries: [...] }` |

## AI Tool Plan

**M3:** Feed the AI my Detection Signals section (signal 1 only) + Architecture diagram + API contract. Ask for Flask skeleton, `POST /submit`, `run_llm_signal()`, audit log, `GET /log`. Verify by calling the signal function directly on a few texts, then curl `/submit` and check `/log`.

**M4:** Feed Detection Signals (both) + Uncertainty Representation + diagram. Ask for `run_stylometric_signal()` and `compute_confidence()`. Verify with the 4 test inputs from the project PDF. Scores should spread across all three bands.

**M5:** Feed label variants + Appeals Workflow + diagram. Ask for `generate_label()`, `POST /appeal`, Flask-Limiter on `/submit`. Verify all 3 labels are reachable, appeals update status, rate limit returns 429 after 10 rapid hits.
