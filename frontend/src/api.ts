/** Typed client for the FastAPI backend (see ../src/intake_approval/api.py). */

export interface CodedRequest {
  category: string;
  cost_centre: string;
  gl_code: string;
  supplier_id: string;
  supplier_name: string;
  amount: number;
}

export interface SupplierMessage {
  to_supplier: string;
  to_requester_id: string;
  purpose: string;
  subject: string;
  body: string;
  sent: boolean;
}

export interface PolicyCheck {
  record_id: string;
  approval_chain: string[];
  tolerance: number;
  three_way: Record<string, unknown>;
  contract: { contract_id: string; supplier_id: string; active: boolean } | null;
}

export interface Packet {
  record_id: string;
  requester_id: string;
  coded_request: CodedRequest;
  policy: PolicyCheck;
  steps: string[];
  supplier_message: SupplierMessage;
  status: string;
  shared: boolean;
  issued: boolean;
}

export interface CaseSummary {
  case_id: string;
  category: string;
  spend_category: string;
  request_text: string;
  requester_id: string;
  requester_name: string;
  approval_limit: number;
  decision: string;
  published: boolean;
  applied: boolean;
  sent: boolean;
  spend_usd: number;
  gates_checked: string[];
  refusal: string;
  flags: Record<string, unknown>;
  provenance: string[];
  packet: Packet | null;
}

export interface AuditEntry {
  seq: number;
  case_id: string;
  tool: string;
  detail: string;
  decision: string;
}

export interface IntakePayload {
  request_text: string;
  requester_id: string;
  category: string;
  approval_limit: number;
}

async function check(response: Response): Promise<unknown> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = (body as { detail?: string }).detail ?? response.statusText;
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json();
}

export async function listCases(): Promise<CaseSummary[]> {
  return (await check(await fetch("/api/cases"))) as CaseSummary[];
}

export async function submitIntake(payload: IntakePayload): Promise<CaseSummary> {
  return (await check(
    await fetch("/api/intake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  )) as CaseSummary;
}

export async function issueCase(caseId: string): Promise<CaseSummary> {
  return (await check(
    await fetch(`/api/cases/${encodeURIComponent(caseId)}/issue`, { method: "POST" }),
  )) as CaseSummary;
}

export async function listAudit(): Promise<AuditEntry[]> {
  return (await check(await fetch("/api/audit"))) as AuditEntry[];
}
