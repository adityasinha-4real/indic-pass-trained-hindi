# Frontend & API

A web interface over the existing IndicPass password-strength engine. This
document covers `api/` and `frontend/` only — everything under `src/`,
`config/`, `data/`, `models/`, `scripts/`, `results/` and `tests/` is
unchanged and is documented elsewhere (`README.md`,
`docs/password_strength_design.md`, `docs/architecture.md`).

**This is a presentation layer, not a second implementation.** Every number
either surface shows was computed by
[`src/indicpass/password/meter.py`](../src/indicpass/password/meter.py) — the
same `IndicPassMeter` class `scripts/check_password.py` has always used. No
password-scoring, transliteration, or attack logic exists in `api/` or
`frontend/`; both are glue and rendering.

```
Browser (frontend/, Next.js)
    |  fetch("http://localhost:8000/api/analyze", { password })
    v
FastAPI adapter (api/main.py)
    |  IndicPassMeter.from_config(load_config())   <- built once, at startup
    |  meter.score(password)                       <- the existing entry point
    v
Existing IndicPass engine (src/indicpass/password/)
    +-- IndicDict (data/dictionaries/indicdict_hin.jsonl)
    +-- PasswordMatcher, scoring.best_segmentation
    +-- PcfgEstimator (data/pcfg/pcfg_hin.json)
    +-- ZxcvbnBaseline (the generic-estimator comparison point)
```

## Why this boundary

`scripts/check_password.py --json` already does exactly what an API needs:
build a meter, score one password, serialise the result without the password
in it. `api/main.py::_serialize` is that same construction — literally the
same two calls (`result.to_dict()`, `describe_dictionaries()` /
`describe_pcfg()`) — so the API and the CLI cannot silently drift apart. See
`api/tests/test_api.py::test_api_result_matches_direct_invocation_exactly`,
which asserts this for several representative passwords by calling both
paths and comparing the parsed JSON.

Nothing in `api/` imports `character_attack.py` or `oov.py`. Those two
(Milestones 4 and 5) are **dataset-level validation harnesses** — they rank a
1,400-password benchmark against a bounded reference attacker and report
aggregate statistics (Spearman correlation, MAE, coverage) in
`results/reports/`. They have no per-password "score one input" entry point,
and building one for this frontend would mean writing new evaluation logic
that does not exist in the frozen research code — exactly what the
preservation rules forbid. The frontend instead shows the two attacks'
already-published findings as static, cited text (see `ResearchNotes.tsx`)
and is explicit that they are not recomputed for whatever you type in.

## Running it

Two processes, both from the project root, in the project's existing
virtual environment.

**Backend**

```bash
python -m pip install -r requirements/api.txt
python -m uvicorn api.main:app --reload --port 8000
```

The first request after startup pays the same cost
`scripts/check_password.py` pays on every invocation — building the
297,747-entry dictionary and refitting the PCFG's character n-gram, on the
order of 20–30 seconds — except here it happens once, in `api.main`'s
`lifespan`, not once per request. `GET /api/health` reports `503` until this
finishes.

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. It talks to `http://localhost:8000` by default;
override with `frontend/.env.local` (see `frontend/.env.local.example`) if
the API runs elsewhere.

## API

One analysis endpoint, plus a health check.

### `POST /api/analyze`

Request:

```json
{ "password": "bharat2024", "reveal_tokens": false }
```

`reveal_tokens` mirrors `check_password.py --show-tokens`: off by default
(matching the CLI's plain `--json` output), and when on, includes the
matched substrings and their Devanagari rendering in the response. It is
never persisted either way — see **Security** below.

Response: exactly what `check_password.py --json` prints for the same
password and the same `reveal_tokens`/`--show-tokens` value — the fields
`PasswordStrengthResult.to_dict()` defines in
[`result.py`](../src/indicpass/password/result.py), plus `dictionaries` and
`estimators` (see `describe_dictionaries` / `describe_pcfg` in `meter.py`).
This project intentionally reuses that existing shape rather than defining a
new one — see `docs/password_strength_design.md` for what each field means.
Representative shape (a `bharat2024` request with `reveal_tokens: true`):

```json
{
  "password_length": 10,
  "guess_number": 21152.0,
  "log10_guesses": 4.325351,
  "strength_score": 1,
  "strength_label": "Weak",
  "indicpass": { "guesses": 21152.0, "score": 1, "label": "Weak", "matches": [ /* ... */ ] },
  "matched_patterns": [ /* per-span breakdown */ ],
  "warnings": [ "Contains a hin dictionary name ..." ],
  "zxcvbn": { "guesses": 137583700.0, "score": 3, "patterns": ["dictionary", "sequence"] },
  "pcfg": { "guesses": 1051690.0, "score": 2, "segments": [ /* ... */ ] },
  "combined_log10_guesses": 4.325351,
  "dictionaries": [ /* IndicDict provenance */ ],
  "estimators": { "indicpass": true, "baseline": "zxcvbn", "pcfg": true }
}
```

The baseline's block is nested under whatever `config/password.yaml`'s
`baseline.implementation` names (`zxcvbn` today) — read it via
`estimators.baseline`, not a hard-coded key (see `getBaselineBlock` in
`frontend/lib/api.ts`).

Errors — never a stack trace or a filesystem path in the body, always a
plain `{"detail": "..."}`:

| Status | When |
| --- | --- |
| 422 | Malformed JSON body / missing `password` field (FastAPI's own validation) |
| 400 | Empty password, or longer than 72 characters |
| 500 | `meter.score()` raised (logged server-side only, via `logger.exception`) |
| 503 | The meter failed to load, or hasn't finished loading yet |

**Why 72 characters, not something rounder:** with the baseline enabled
(the shipped default), every call also runs `zxcvbn`, which hard-codes a
72-character cap of its own and raises `ValueError` above it. Rejecting an
over-length request here with a clear 400 is strictly better than the 500
that same input would otherwise produce two calls deeper — the bound
describes an existing limit of the composed system, not a new one invented
for this API. It surfaced during manual end-to-end testing of this feature,
not from reading the zxcvbn source in advance.

### `GET /api/health`

`{"status": "ok", "ready": true}`, or `503` with a `detail` while the meter
is still loading or failed to load. No stack trace or path in either case;
the real exception goes to the server log via `logger.exception`.

## Security

- A password reaches the API only as a POST JSON body — never a URL, a
  query string, or a header.
- Nothing under `api/` or `frontend/` writes a password to a file, a
  database, or a log line. The one thing an analysis failure logs is the
  exception (`logger.exception`), which is over the meter's internal state,
  not the request body.
- `frontend/lib/api.ts` is the only module that calls the backend; it does
  not use `localStorage`, `sessionStorage`, cookies, or any analytics
  library. `AnalyzerSection.tsx` holds the password in React state only,
  cleared by the Clear button and never written to a browser storage API.
- CORS is restricted to `http://localhost:3000` / `127.0.0.1:3000` by
  default (`INDICPASS_API_CORS_ORIGINS` in `api/.env` to change it) —
  there is no wildcard origin.
- No rate limiting is implemented. This is a local research demo over a
  frozen, non-secret dataset; adding one was judged unnecessary complexity
  per the brief this frontend was built against, not an oversight.
- `MAX_PASSWORD_LENGTH` (72, see above) is the only adapter-level input
  bound; it rejects oversized input before it reaches the meter rather than
  changing anything about how the meter handles length.

## Tests

```bash
python -m pytest              # unchanged: 785 tests in tests/, ~none touched
python -m pytest api/tests    # new: the API adapter, ~1 minute (see below)
cd frontend && npm run build  # type-checks + production build
cd frontend && npm run lint   # ESLint
```

`api/tests/` is intentionally **not** under `tests/` and is not on
`pyproject.toml`'s `testpaths` — adding it there would have required editing
the root pytest configuration that the rest of the project's test count is
measured against. Keeping it a sibling directory (with its own
`api/tests/conftest.py` for `sys.path`, mirroring `scripts/_bootstrap.py`'s
own approach) means `python -m pytest` from the project root is byte-for-byte
the same command with the same collected tests as before this feature
existed.

`api/tests/test_api.py` covers:

- **Equivalence** (the test that matters): for seven representative
  passwords, `POST /api/analyze`'s parsed JSON equals
  `json.loads(_serialize(direct_meter.score(password), direct_meter, ...))`
  from an independently constructed `IndicPassMeter` — not the same object
  the running app built, so this also exercises that construction is
  deterministic from the committed config and artefacts.
- Malformed/edge-case requests (missing field, empty password, over-length
  password, invalid JSON body) return the documented status codes, never a
  500 or a leaked path/traceback.
- `reveal_tokens` changes only which redacted fields are present, never a
  number (`test_redacted_and_revealed_payloads_agree_on_every_numeric_field`).

This file builds two full `IndicPassMeter`s (the running app's, plus
`direct_meter`), so it costs roughly what two `check_password.py`
invocations cost — about a minute — which is why it stays out of the default
test run rather than slowing down every `python -m pytest`.

## Known constraints

- **72-character password ceiling** (above). Anything the meter itself could
  score past that point is unreachable through this API while the zxcvbn
  baseline stays enabled; using the CLI directly, or a meter built with
  `with_baseline=False`, has no such limit.
- **`Infinity` in the JSON body.** `PasswordStrengthResult.guess_number` can
  be `math.inf` for an unstructured password whose guess count overflows a
  float (see `guesses_from_log10` in `result.py`) — `json.dumps` (used here,
  same as the CLI) emits the bare, non-standard `Infinity` token for it.
  `frontend/lib/api.ts::parseIndicPassJson` handles this on the way in, so
  the UI reads it as `Number.POSITIVE_INFINITY` and renders "effectively
  unlimited" rather than throwing. A generic JSON client (`curl | jq`,
  `response.json()` in another app) will not parse this response as-is for
  such an input; that is an existing property of the CLI's own `--json`
  output, not something introduced here.
- No streaming/partial results — `POST /api/analyze` returns once scoring
  finishes, which for one password is a dictionary lookup and is fast; the
  slow part (dictionary load, PCFG refit) happens once at server startup.
