# Frontend — React/TypeScript surface for the intake-approval agent

A small, real surface over the FastAPI backend (`../src/intake_approval/api.py`):

- **Intake** — a one-sentence purchase request goes in; the coded request
  (category, cost centre, GL code, supplier) comes out. Submitting is
  gate 1: the packet may be prepared and queued for approvers. Nothing
  is issued or sent.
- **Approval queue** — every case the agent has seen (the 48 frozen eval
  cases, seeded at startup, plus any case submitted through the form),
  with its decision, draft status and gate state. A PROPOSE case shows an
  **Issue (gate 2)** button: the second explicit confirmation before a
  PO is issued and the supplier is messaged.
- **Audit** — the real audit trail: every tool call, in order.

## Run

```bash
npm ci
npm run build        # type-checks (tsc --noEmit) and builds to dist/
npm run dev          # Vite dev server; /api is proxied to localhost:8000
```

Serve the built bundle from the API:

```bash
cd ..                # repo root
pip install -e .
uvicorn intake_approval.api:app --reload   # serves frontend/dist at /
```

The API checks for `frontend/dist` at request time, so the bundle is
served as soon as `npm run build` has run — no API restart needed.

## Scope

This is a small surface, not a demo skin: the form submits to the real
API, the queue shows real cases, the audit view shows real audit
entries. All data is synthetic (Cascade Manufacturing Group) and the
agent never commits spend or sends anything without the two gates.
