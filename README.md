# Provenance Guard

Backend that guesses whether text is human or AI, gives a confidence score and plain-language label, and lets creators appeal bad calls.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# Add your GROQ_API_KEY to .env
python app.py
```

Server runs at `http://localhost:5000`.

## Dashboard (easiest way to test)

Open `http://localhost:5000/dashboard`.

**Layout:**
- **Submit content** (left) and **Appeal result** (right) side by side
- **Verify creator** button opens a modal for the provenance certificate stretch feature
- **Classification result** below shows request payload, response JSON, attribution, and a verified checkmark when applicable
- **Analytics** at the bottom update live after each action

**Typical demo flow:**
1. Submit a few contrasting texts (human, AI, uncertain)
2. Appeal an uncertain result from the right panel
3. Open verify modal, verify a creator with a casual writing sample
4. Submit again with the same creator ID to show `creator_badge` on the response
5. Open `GET /log` to show the audit trail

Note: `creator_badge` is identity-level trust. A verified creator can still post content classified as likely AI.

## Architecture Overview

1. Client sends `POST /submit` with `text` and `creator_id`.
2. Flask-Limiter checks 10/min and 100/day caps. Over limit returns 429.
3. Signal 1 (Groq LLM) returns `llm_score` (0-1, higher = more AI-like).
4. Signal 2 (stylometric heuristics) returns `stylometric_score`.
5. Signal 3 (burstiness, stretch) returns `burstiness_score`. Logged every time.
6. Confidence scoring combines signals 1 and 2 with 60/40 weighting.
7. Label generator picks plain-language text for the result.
8. SQLite stores everything. JSON response goes back to the client.

Appeals: creator hits `POST /appeal` (or the dashboard form) with `content_id`, `creator_id`, and `creator_reasoning`. Status becomes `under_review`. Check `GET /log` to review.

## API Endpoints

| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| `/submit` | POST | `{ text, creator_id }` or metadata payload | `{ content_id, attribution, confidence, label, creator_badge }` |
| `/appeal` | POST | `{ content_id, creator_id, creator_reasoning }` | `{ message, content_id, status }` |
| `/log` | GET | none | `{ entries: [...] }` |
| `/verify` | POST | `{ creator_id, sample_text }` | `{ verified_human, creator_id, message }` |
| `/dashboard` | GET | none | HTML submit form, appeal form, analytics |
| `/stats` | GET | none | JSON analytics for the dashboard |

### Example submit

```powershell
curl -s -X POST http://localhost:5000/submit `
  -H "Content-Type: application/json" `
  -d '{"text": "Your content here.", "creator_id": "user-1"}'
```

## Detection Signals

### Signal 1: Groq LLM (`llama-3.3-70b-versatile`)

Reads the text and returns how AI-like it feels.

**Why:** catches polished generic AI writing that heuristics miss.

**Blind spot:** formal human essays can look too clean and score mid-high.

### Signal 2: Stylometric heuristics (pure Python)

Sentence length variance, transition phrases (`furthermore`, `it is important to note`), type-token ratio, contractions.

**Why:** AI text is usually more structurally uniform.

**Blind spot:** repetitive minimalist poetry tanks vocab diversity scores.

### Signal 3: Burstiness (stretch, pure Python)

Bigram repetition and word frequency skew. Logged as `burstiness_score`. Optional 50/30/20 ensemble when `use_ensemble=True`.

## Confidence Scoring

**Default formula:**
```
confidence = 0.6 * llm_score + 0.4 * stylometric_score
```

**Thresholds:**

| Range | Attribution |
|-------|-------------|
| >= 0.80 | `likely_ai` |
| <= 0.30 | `likely_human` |
| 0.30 to 0.80 | `uncertain` |

AI threshold is higher on purpose. False positives on human writers are worse than missing AI.

Tested the four spec examples (clear AI, clear human, formal human, lightly edited AI). Scores land in different bands.

### Example submissions

**High-confidence AI** (confidence 0.811):
```json
{
  "attribution": "likely_ai",
  "confidence": 0.811,
  "label": "Likely AI-generated. Our analysis found strong signs of automated writing (confidence: 81%). This is a high-confidence call, not a guarantee."
}
```

**Uncertain** (confidence 0.562):
```json
{
  "attribution": "uncertain",
  "confidence": 0.562,
  "label": "Attribution uncertain. We couldn't confidently tell if this is human or AI (confidence: 56%). Creators can appeal this result."
}
```

**High-confidence human** (confidence 0.107):
```json
{
  "attribution": "likely_human",
  "confidence": 0.107,
  "label": "Likely human-written. Our analysis found strong signs of authentic, personal writing (confidence: 89%). This is a high-confidence call, not a guarantee."
}
```

0.51 and 0.95 produce different labels. That was the whole point.

## Transparency Labels

Exact text for each variant:

**High-confidence AI:**
> "Likely AI-generated. Our analysis found strong signs of automated writing (confidence: {pct}%). This is a high-confidence call, not a guarantee."

**High-confidence human:**
> "Likely human-written. Our analysis found strong signs of authentic, personal writing (confidence: {pct}%). This is a high-confidence call, not a guarantee."

**Uncertain:**
> "Attribution uncertain. We couldn't confidently tell if this is human or AI (confidence: {pct}%). Creators can appeal this result."

Verified creators also see: ` · Verified Human Creator`

The badge reflects **creator identity** (passed `/verify`), not the classification of the current post. A verified creator submitting AI-sounding text can still get `likely_ai` with `creator_badge: "verified_human"`.

## Rate Limiting

`/submit` is limited to **10 requests per minute** and **100 per day** per IP.

**Why those numbers:** a writer might submit a few drafts in one sitting. 10/min is plenty. 100/day stops scripted flooding.

**Test output** (12 rapid requests):

```
200 200 200 200 200 200 429 429 429 429 429 429
```

The 11th `/submit` in a minute returns HTTP 429.

## Appeals Workflow

Creators appeal with `content_id`, matching `creator_id`, and `creator_reasoning`.

The system:
1. Checks the submission exists and the creator matches.
2. Sets status to `under_review`.
3. Logs `appeal_reasoning` and `appeal_timestamp` next to the original call.

No auto re-classification. A human reviewer checks `GET /log`.

**Dashboard:** submit on the left. Appeal on the right (enabled after first submit). Request/response JSON appears in the classification result panel.

**API:**
```powershell
curl -s -X POST http://localhost:5000/appeal `
  -H "Content-Type: application/json" `
  -d '{"content_id": "YOUR-ID", "creator_id": "user-1", "creator_reasoning": "I wrote this myself."}'
```

## Audit Log

Every submission and appeal goes into SQLite. Pull it with `GET /log`.

Sample classified entry:

```json
{
  "content_id": "b5d242e4-82c6-44a3-a264-4a0cecd26099",
  "creator_id": "test-user-1",
  "timestamp": "2026-06-28T19:29:25.511902+00:00",
  "attribution": "likely_ai",
  "confidence": 0.811,
  "llm_score": 0.92,
  "stylometric_score": 0.648,
  "burstiness_score": 0.042,
  "status": "classified",
  "label": "Likely AI-generated. Our analysis found strong signs of automated writing (confidence: 81%). This is a high-confidence call, not a guarantee."
}
```

Sample appealed entry:

```json
{
  "content_id": "9ac01259-3c5e-4f4f-93a4-becad5b64893",
  "creator_id": "test-user-2",
  "attribution": "likely_human",
  "confidence": 0.107,
  "llm_score": 0.12,
  "stylometric_score": 0.087,
  "status": "under_review",
  "appeal_reasoning": "I wrote this after actually going to the restaurant.",
  "appeal_timestamp": "2026-06-28T19:29:00.450055+00:00"
}
```

## Stretch Features

### Ensemble detection
Burstiness runs on every submission. Optional 3-signal weighting: `0.50*llm + 0.30*stylometric + 0.20*burstiness`.

### Provenance certificate
`POST /verify` grants a verified badge when a writing sample scores likely human with confidence <= 0.25. Dashboard: click **Verify creator** to open the modal. Shows request/response JSON and a checkmark on success. Badge appears on future `/submit` responses for that `creator_id`, independent of each post's attribution.

### Analytics dashboard
`GET /dashboard` shows detection breakdown, appeal rate, and average confidence. Side-by-side submit and appeal forms, verify modal, classification result with JSON payload/response, live stats via `GET /stats`.

### Multi-modal support
`/submit` accepts `content_type: "metadata"` with `metadata: { title, tags, author_bio }`. Good for photo posts where you only have a caption and tags, not a full article. Same text pipeline, different scoring weights.

```json
{
  "creator_id": "photographer",
  "content_type": "metadata",
  "metadata": {
    "title": "Sunset at the Pier",
    "tags": "photography, golden hour",
    "author_bio": "Amateur photographer in Portland"
  }
}
```

## Known Limitations

**Repetitive minimalist poetry** will probably score too high on stylometrics. Short repeated lines wreck the type-token ratio even when a human wrote it. Uncertain band + appeals help but do not fix it completely.

**Formal human writing** (academic prose) can also land uncertain because it looks structurally clean. That is intentional. We would rather flag uncertainty than wrongly call a human essay AI.

## Spec Reflection

**How the spec helped:** building one signal at a time (M3 then M4) made it way easier to debug weird scores.

**Where I diverged:** burstiness is logged on every submission but the live classifier still uses 60/40 LLM + stylometrics. Full ensemble pulled obvious AI text into uncertain during testing.

## AI Usage

1. **Flask skeleton + Signal 1:** fed planning.md detection signals + architecture diagram to an AI tool. It returned a binary flag first. I fixed it to return a 0-1 float.

2. **Stylometrics + scoring:** AI-generated the second signal and combiner. Type-token ratio was overweighted and flagged AI as human. I rewrote weights to lean on transition phrases and formality.

3. **Dashboard UI:** asked AI to build `/dashboard` with side-by-side submit/appeal forms, verify modal, JSON payload/response display, and verified checkmark. Used for demo instead of curl.

## Project Structure

```
app.py
labels.py
scoring.py
signals/
  llm_signal.py
  stylometric_signal.py
  burstiness_signal.py
storage/
  db.py
templates/
  dashboard.html
planning.md
```
