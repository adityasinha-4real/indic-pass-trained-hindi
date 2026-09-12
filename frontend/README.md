# IndicPass frontend

A Next.js interface over the IndicPass password-strength engine. This app
contains **no analysis logic** — every number it shows came from
`src/indicpass/password/` by way of `POST /api/analyze` in [`../api/`](../api/).
See [`../docs/frontend.md`](../docs/frontend.md) for the full architecture,
API contract and security notes.

## Run it

Requires Node 18.18+ and the IndicPass API running (see `../api/README.md` or
`../docs/frontend.md`).

```bash
npm install
cp .env.local.example .env.local   # only needed if the API isn't on localhost:8000
npm run dev
```

Open http://localhost:3000.

## Structure

```
app/            Next.js App Router pages, layout, global styles
components/     Presentational + one client component (AnalyzerSection) that
                owns the form/loading/error/result state
lib/            api.ts (the only module that calls the backend), types.ts
                (mirrors the API's JSON shape), format.ts, labels.ts
```

## Build

```bash
npm run build
npm run start
```
