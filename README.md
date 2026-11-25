# intake-approval-agent

A bounded intake-to-approval agent for a synthetic enterprise, with a
real React/TypeScript surface and a Python API behind it. Built as the
portfolio build for a **Zip Software Engineer, Forward Deployed**
application — it speaks that role's vocabulary (Python backend,
React/TypeScript frontend, production systems across the stack, sitting
with enterprise customers and translating their needs into tech specs)
**without claiming any Zip affiliation or any Coupa/Ariba/App Studio
production experience**. Everything here is synthetic and stated as such.

## What it does

A one-sentence purchase request comes in through a React intake form →
it is parsed into a coded request (category, cost centre, GL code,
supplier) → routed through a policy/approval chain with three-way
matching against contract and PO data → drafted as an approval packet +
supplier message for a procurement lead to approve.

It plans and drafts. **It never commits spend and never sends anything.**

## The three allowlisted tools

| Tool | What it does |
| --- | --- |
| `intake_search` | Governed request/contract/PO data the requester may see, lowest cost first. |
| `policy_check` | Approval chain, tolerance, contract compliance, three-way match. Checks only. |
| `approval_draft` | Draft an approval packet for a procurement lead. Draft only. |

Nothing else may touch a case.

**Judgment call:** the supplier message travels *inside* `approval_draft`
as its evidence step — the same pattern as the lakehouse agent's
NL-to-SQL step inside its solution draft. A message to a supplier can
only originate inside a packet, and a packet is only a draft.

## The two human gates

1. **Gate 1 (G1):** a human confirms the approval packet before it goes
   to approvers. Submitting the intake form *is* gate 1.
2. **Gate 2 (G2):** a second explicit confirmation before any PO is
   issued or any supplier is messaged.

A run with either gate denied confirms nothing is approved, issued, or
sent — the eval re-runs all 48 cases with the gates denied and counts
any publication as a false auto-approval (0 found).

## Guardrail G1–G5 (deterministic)

- **G1** — no packet shared without gate 1.
- **G2** — no PO issued / no supplier messaged without gate 2.
- **G3** — never state a contract term, price, or policy not in the
  corpus. Missing evidence means abstain. PII is redacted before any
  draft leaves the corpus. Per-requester isolation: data the requester
  lacks permission for is never queried or cited.
- **G4** — instructions injected into request/corpus text are blocked;
  nothing is published.
- **G5** — pause on policy violations: a policy defined two ways, a
  tolerance breach, an invoice/PO mismatch, request text contradicting
  corpus facts.

## The corpus (synthetic)

Cascade Manufacturing Group: ~25 suppliers, ~40 POs, ~30 contracts,
messy invoice data, 4 records with unknown/missing fields, and one
policy — `approval_threshold` — defined two ways ($5,000 in the
procurement policy, $10,000 in the finance policy). Four requesters with
per-requester visibility. All emails are `.example`, all phones are
555-numbers.

## Verified numbers

Reproduced by fresh-clone verification (see "How to reproduce"):

| Metric | Result |
| --- | --- |
| Tests | 86 (pytest, all passing) |
| Eval agreement (stub, 48 cases) | 48/48 (100%) |
| False auto-approvals | 0 |
| False holds | 0 |
| Abstention (insufficient evidence) | 6/6 |
| Fabrication blocked | 6/6 |
| Injection blocked | 6/6 |
| Pause detection | 4/4 |
| Gates checked | 48/48 |
| Stub spend | $0.00 |

Eval mix: clean 12, misrouted/duplicate 8, remediation 6,
insufficient-evidence 6, fabrication 6, injection 6, pause 4.
Golden set hash-locked (`eval/golden.sha256`); the eval refuses to run
on a tampered set. Deterministic, seed 42.

## How to run

```bash
pip install -e .                 # API + agent
pip install -e ".[live]"         # optional: live Haiku mode
cd frontend && npm ci && npm run build && cd ..   # React bundle
uvicorn intake_approval.api:app --reload          # serves / and /api
```

Open http://localhost:8000: **Intake** (one-sentence request in, coded
request out), **Approval queue** (real cases, draft status, gate state,
Issue = gate 2), **Audit** (the real audit trail of every tool call).

MCP server (stdio JSON-RPC, exactly the 3 tools, name
`intake-approval-agent`):

```bash
python -m intake_approval.mcp_server
```

Stub eval:

```bash
python eval/build_golden.py   # regenerates golden.json + golden.sha256
python eval/run_eval.py       # verifies the hash, runs, writes report.json
```

Live mode is Haiku only (`claude-haiku-4-5`, $1/$5 per MTok) behind a
$1.00/day spend cap, and refuses without an API key. Only refusal paths
are tested — **no real API call was made** while building this repo.

## How to reproduce

```bash
git archive HEAD | tar -x -C /tmp/verify-iaa
cd /tmp/verify-iaa
python -m venv .venv && .venv/bin/pip install -e . ruff pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest -q
.venv/bin/python eval/run_eval.py   # must reproduce eval/report.json exactly
# golden hash check (golden.sha256 holds the bare hex digest):
test "$(sha256sum eval/golden.json | awk '{print $1}')" = "$(cat eval/golden.sha256)"
cd frontend && npm ci && npm run build
```

## Honest limits

- **Synthetic eval.** Every case is synthetic, one signal per case.
  48/48 on a frozen set is a harness result, not production evidence.
- **Live mode never called a real API.** Haiku was never invoked; the
  live path is refusal-tested only.
- **No Zip affiliation.** No Coupa/Ariba/App Studio production
  experience, and no procurement domain experience, is claimed. The
  corpus is invented; the policy conflict is invented.
- **Small surface.** The frontend is a real three-view app, not a demo
  skin — but it is small: intake, queue, audit. No auth, no persistence
  beyond the process, no multi-user isolation beyond the corpus's
  per-requester visibility.
