# IndicPass API

A thin FastAPI adapter over the existing IndicPass password-strength engine
(`src/indicpass/password/`). It contains no analysis logic of its own — see
[`../docs/frontend.md`](../docs/frontend.md) for the architecture, the exact
request/response contract, and the security guarantees.

## Run it

From the project root, with the same virtual environment the rest of
IndicPass uses:

```bash
python -m pip install -r requirements/api.txt
python -m uvicorn api.main:app --reload --port 8000
```

First request after startup builds the dictionary and refits the PCFG grammar
(tens of seconds — the same cost `scripts/check_password.py` pays on every
invocation); this happens once, at process startup, not per request.

- `POST /api/analyze` — `{"password": "...", "reveal_tokens": false}` →
  the same JSON `scripts/check_password.py --json` prints.
- `GET /api/health` — `{"status": "ok", "ready": true}`, or `503` while the
  meter is still loading or failed to load.
- `GET /docs` — interactive Swagger UI (FastAPI's default).

## Tests

```bash
python -m pytest api/tests
```

Kept out of the default `python -m pytest` run (which stays scoped to
`tests/`, unchanged) because these tests build a real `IndicPassMeter` twice
— once via the running app, once directly — to check the two agree exactly;
that costs roughly a minute, entirely from loading the dictionary and PCFG
artefacts.
