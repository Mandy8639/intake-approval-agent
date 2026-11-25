import { useCallback, useEffect, useState } from "react";
import {
  issueCase,
  listAudit,
  listCases,
  submitIntake,
  type AuditEntry,
  type CaseSummary,
} from "./api";

const REQUESTERS = [
  { id: "REQ-01", name: "Dana Ortiz — Procurement Lead" },
  { id: "REQ-02", name: "Samir Patel — Finance Manager" },
  { id: "REQ-03", name: "Elena Ruiz — IT Procurement Analyst" },
  { id: "REQ-04", name: "Tom Becker — External Auditor" },
];

const CATEGORIES = [
  "it_hardware",
  "office_supplies",
  "professional_services",
  "facilities",
  "general",
];

type Tab = "intake" | "queue" | "audit";

function GateState({ c }: { c: CaseSummary }) {
  return (
    <span>
      gate 1 {c.published ? "confirmed" : "pending"} · gate 2{" "}
      {c.applied ? "confirmed" : "pending"}
    </span>
  );
}

function PacketView({ c }: { c: CaseSummary }) {
  if (!c.packet) {
    return (
      <p className="muted">
        No packet — the agent {c.decision.toLowerCase()} this case
        {c.refusal ? `: ${c.refusal}` : ""}. Flags:{" "}
        <code>{JSON.stringify(c.flags)}</code>
      </p>
    );
  }
  const p = c.packet;
  return (
    <div className="packet">
      <h3>
        Approval packet — {p.record_id} <span className="muted">({p.status})</span>
      </h3>
      <dl>
        <dt>Supplier</dt>
        <dd>
          {p.coded_request.supplier_name} ({p.coded_request.supplier_id})
        </dd>
        <dt>Amount</dt>
        <dd>${p.coded_request.amount.toLocaleString()}</dd>
        <dt>Cost centre / GL</dt>
        <dd>
          {p.coded_request.cost_centre} · {p.coded_request.gl_code}
        </dd>
        <dt>Approval chain</dt>
        <dd>{p.policy.approval_chain.join(" → ")}</dd>
        <dt>Three-way match</dt>
        <dd>
          <code>{JSON.stringify(p.policy.three_way)}</code>
        </dd>
        <dt>Contract</dt>
        <dd>
          {p.policy.contract
            ? `${p.policy.contract.contract_id} (active: ${p.policy.contract.active})`
            : "none in this case"}
        </dd>
      </dl>
      <h4>Steps</h4>
      <ol>
        {p.steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
      <h4>Supplier message (draft — never sent without gate 2)</h4>
      <p>
        <strong>{p.supplier_message.subject}</strong>
      </p>
      <pre>{p.supplier_message.body}</pre>
      <p className="muted">
        Provenance: {c.provenance.join(", ") || "none"} · Spend: $
        {c.spend_usd.toFixed(2)}
      </p>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("intake");
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [requestText, setRequestText] = useState(
    "Order 12 laptops for the design team.",
  );
  const [requesterId, setRequesterId] = useState("REQ-01");
  const [category, setCategory] = useState("it_hardware");
  const [approvalLimit, setApprovalLimit] = useState(10000);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [nextCases, nextAudit] = await Promise.all([listCases(), listAudit()]);
    setCases(nextCases);
    setAudit(nextAudit);
  }, []);

  useEffect(() => {
    refresh().catch((err: unknown) =>
      setError(err instanceof Error ? err.message : String(err)),
    );
  }, [refresh]);

  const selected = cases.find((c) => c.case_id === selectedId) ?? null;

  async function onSubmit() {
    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const created = await submitIntake({
        request_text: requestText,
        requester_id: requesterId,
        category,
        approval_limit: approvalLimit,
      });
      setSelectedId(created.case_id);
      setNotice(
        `Case ${created.case_id} queued: ${created.decision}. ` +
          `Gate 1 confirmed by this submit; nothing is issued or sent.`,
      );
      await refresh();
      setTab("queue");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function onIssue(caseId: string) {
    setError(null);
    setNotice(null);
    try {
      const updated = await issueCase(caseId);
      setNotice(
        `Case ${caseId} issued: PO issued and supplier messaged ` +
          `(gate 2 confirmed).`,
      );
      setCases((prev) => prev.map((c) => (c.case_id === caseId ? updated : c)));
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <div className="shell">
      <header>
        <h1>Intake Approval Agent</h1>
        <p className="muted">
          Cascade Manufacturing Group · synthetic spend corpus · the agent plans
          and drafts; it never commits spend and never sends anything without
          two human confirmations.
        </p>
      </header>

      <nav className="tabs">
        {(["intake", "queue", "audit"] as Tab[]).map((t) => (
          <button
            key={t}
            className={tab === t ? "active" : ""}
            onClick={() => setTab(t)}
          >
            {t === "intake" ? "Intake" : t === "queue" ? `Approval queue (${cases.length})` : "Audit"}
          </button>
        ))}
      </nav>

      {error && <p className="error">Error: {error}</p>}
      {notice && <p className="notice">{notice}</p>}

      {tab === "intake" && (
        <section>
          <h2>New purchase request</h2>
          <p className="muted">
            One sentence in, a coded request out. Submitting is gate 1: you
            confirm the packet may be prepared and queued for approvers.
          </p>
          <label>
            Request (one sentence)
            <input
              value={requestText}
              onChange={(e) => setRequestText(e.target.value)}
              placeholder="Order 12 laptops for the design team."
            />
          </label>
          <label>
            Requester
            <select value={requesterId} onChange={(e) => setRequesterId(e.target.value)}>
              {REQUESTERS.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Category
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label>
            Approval limit ($)
            <input
              type="number"
              min={1}
              value={approvalLimit}
              onChange={(e) => setApprovalLimit(Number(e.target.value))}
            />
          </label>
          <button onClick={onSubmit} disabled={submitting || !requestText.trim()}>
            {submitting ? "Submitting…" : "Submit request (gate 1)"}
          </button>
        </section>
      )}

      {tab === "queue" && (
        <section>
          <h2>Approval queue</h2>
          <table>
            <thead>
              <tr>
                <th>Case</th>
                <th>Request</th>
                <th>Decision</th>
                <th>Gates</th>
                <th>Packet</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr
                  key={c.case_id}
                  className={selectedId === c.case_id ? "selected" : ""}
                  onClick={() => setSelectedId(c.case_id)}
                >
                  <td>{c.case_id}</td>
                  <td>{c.request_text}</td>
                  <td>{c.decision}</td>
                  <td>
                    <GateState c={c} />
                  </td>
                  <td>{c.packet ? c.packet.record_id : "—"}</td>
                  <td>
                    {c.decision === "PROPOSE" && !c.applied && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void onIssue(c.case_id);
                        }}
                      >
                        Issue (gate 2)
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {selected && <PacketView c={selected} />}
        </section>
      )}

      {tab === "audit" && (
        <section>
          <h2>Audit trail</h2>
          <p className="muted">
            Every tool call the agent made, in order. Nothing is issued or sent
            without the two gates.
          </p>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Case</th>
                <th>Tool</th>
                <th>Detail</th>
                <th>Decision</th>
              </tr>
            </thead>
            <tbody>
              {audit.map((entry) => (
                <tr key={entry.seq}>
                  <td>{entry.seq}</td>
                  <td>{entry.case_id}</td>
                  <td>{entry.tool}</td>
                  <td>{entry.detail}</td>
                  <td>{entry.decision}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
