// Everything the app knows about the backend lives here: the shapes of the responses and
// one small function per endpoint. Amounts of money arrive as text ("180000.00") and stay
// text; see format.ts for how they are displayed.

export type Decision = 'APPROVE' | 'REVIEW' | 'REJECT'
export type RunState =
  | 'processing'
  | 'approved'
  | 'awaiting_review'
  | 'approved_by_reviewer'
  | 'rejected_by_reviewer'
  | 'rejected'
  | 'failed'
export type StageName = 'receive' | 'extract' | 'validate' | 'match' | 'rules' | 'decide'
export type Money = string

export interface Resolution {
  action: 'approved' | 'rejected'
  comment: string
  resolved_at: string
}

export interface RunSummary {
  id: string
  created_at: string
  finished_at: string | null
  file_name: string
  source: 'upload' | 'sample'
  status: 'queued' | 'running' | 'completed' | 'failed'
  state: RunState
  decision: Decision | null
  headline: string | null
  owner: string | null
  owner_label: string | null
  vendor_id: string | null
  vendor_name: string | null
  invoice_number: string | null
  invoice_date: string | null
  pretax_amount: Money | null
  gross_amount: Money | null
  po_id: string | null
  failed_stage: StageName | null
  error_message: string | null
  resolution: Resolution | null
}

export interface Finding {
  code: string
  stage: string
  status: 'pass' | 'warn' | 'fail' | 'skipped'
  severity: 'info' | 'review' | 'reject'
  message: string
  owner: 'ap' | 'procurement' | 'vendor' | 'none'
  // The values the check used. Different for every check, so read with care.
  data: Record<string, any>
}

export interface Stage {
  stage: StageName
  uses_ai: boolean
  status: 'waiting' | 'running' | 'done' | 'failed' | 'not_run'
  started_at: string | null
  duration_ms: number | null
  // Each stage has its own result shape; the typed versions are below.
  result: Record<string, any> | null
  findings: Finding[]
}

export interface Reason {
  code: string
  text: string
  severity: 'info' | 'review' | 'reject'
  status: 'warn' | 'fail'
  owner: string
}

export interface DecisionDetail {
  decision: Decision
  headline: string
  reasons: Reason[]
  owner: string
  owner_label: string
  next_action: string
  passed: string[]
  not_checked: string[]
}

export interface RunDetail extends RunSummary {
  file_hash: string
  pages: string[]
  stages: Stage[]
  total_duration_ms: number | null
  decision_detail: DecisionDetail | null
}

// --- Stage results ---------------------------------------------------------------------

export interface ReceiveResult {
  file_name: string
  file_hash: string
  size_bytes: number
  page_count: number
  seen_before: boolean
  note: string | null
}

export interface LineItem {
  description: string | null
  quantity: string | null
  unit_price: Money | null
  amount: Money | null
}

export interface InvoiceRecord {
  document_type: string
  vendor_name: string | null
  vendor_tax_id: string | null
  invoice_number: string | null
  invoice_date: string | null
  date_is_ambiguous: boolean
  po_reference: string | null
  currency: string | null
  line_items: LineItem[]
  subtotal: Money | null
  tax_amount: Money | null
  tax_rate_percent: string | null
  amounts_tax_inclusive: boolean
  total: Money | null
  evidence?: Record<string, string | null> | null
  notes?: string | null
}

export interface ExtractResult {
  record: InvoiceRecord
  source: 'live' | 'reused_identical_file' | 'saved_live_failed' | 'saved_daily_cap'
  label: string
  model: string | null
  input_tokens: number | null
  output_tokens: number | null
  live_error: string | null
  saved_at: string | null
}

export interface ValidateResult {
  pretax_amount: Money | null
  gross_amount: Money | null
  pretax_source: string
  invoice_date: string | null
}

export interface POCandidate {
  po_id: string
  score: number
  amount_fits: boolean
  description_similarity: number
  date_ok: boolean
  strong: boolean
  evidence: string[]
}

export interface MatchResult {
  vendor_id: string | null
  vendor_name: string | null
  vendor_match: 'tax_id' | 'name' | 'suggested' | 'none'
  po_id: string | null
  po_match_type:
    | 'explicit_verified'
    | 'explicit_conflict'
    | 'not_found'
    | 'implied_single'
    | 'implied_multiple'
    | 'none'
  po: {
    po_id: string
    vendor_id: string
    status: string
    value: Money
    billed_to_date: Money
    remaining: Money
    earlier_invoices: {
      invoice_number: string | null
      invoice_date: string | null
      pretax_amount: Money | null
      state: string
    }[]
  } | null
  candidates: POCandidate[]
  line_pairs: {
    invoice_line: number
    description: string
    po_line_no: number | null
    po_description: string | null
    score: number
  }[]
}

export interface DuplicateLink {
  kind: 'exact' | 'probable'
  invoice_id: number | null
  invoice_number: string | null
  file_name: string
  reason: string
}

export interface RulesResult {
  duplicates: DuplicateLink[]
  po_overage: Money | null
}

// --- Lists and reference data ----------------------------------------------------------

export interface SeededInvoice {
  invoice_number: string | null
  vendor_id: string | null
  vendor_name: string | null
  po_id: string | null
  invoice_date: string | null
  pretax_amount: Money | null
  gross_amount: Money | null
  state: string
  file_name: string
}

export interface RunList {
  runs: RunSummary[]
  seeded_history: SeededInvoice[]
}

export interface Stats {
  total_runs: number // every run, including failed ones and ones in progress
  processed: number // runs that reached a decision
  approved: number // by the process or by a reviewer
  auto_approved: number
  auto_approved_percent: number | null
  approved_by_reviewer: number
  awaiting_review: number
  rejected: number // by the process or by a reviewer
  rejected_by_process: number
  rejected_by_reviewer: number
  failed: number
  in_progress: number
  value_approved_pretax: Money
  value_approved_gross: Money
  seeded_invoices: number
}

export interface Sample {
  case: number
  file: string
  description: string
  scanned: boolean
  tag: string // a short label for the gallery card; display only, never sent with a run
}

export interface POInvoice {
  invoice_number: string | null
  invoice_date: string | null
  pretax_amount: Money | null
  gross_amount: Money | null
  state: 'approved' | 'awaiting_review' | 'rejected'
  is_seeded: boolean
  run_id: string | null
  file_name: string
}

export interface InvoiceDetail extends POInvoice {
  id: number
  vendor_id: string | null
  vendor_name: string | null
  po_id: string | null
  pages: string[]
  record: InvoiceRecord | null
}

export interface PurchaseOrder {
  id: string
  vendor_id: string
  vendor_name: string
  po_date: string
  status: string
  value: Money
  billed_to_date: Money
  remaining: Money
  lines: { line_no: number; description: string; quantity: string; unit_price: Money; amount: Money }[]
  invoices: POInvoice[]
}

export interface Rules {
  validate: { rounding_tolerance_rupees: string; max_invoice_age_days: number; currency: string }
  match: {
    vendor_name_suffixes: string[]
    vendor_fuzzy_min_score: number
    line_match_min_score: number
    implied_po_points_amount_fits: number
    implied_po_points_description: number
    implied_po_points_date: number
    implied_po_strong_score: number
  }
  rules: {
    po_overage_max_percent: string
    po_overage_max_rupees: string
    price_variance_max_percent: string
    duplicate_max_extra_characters: number
  }
}

// --- Calls -----------------------------------------------------------------------------

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

/** One request to the backend. Turns any failure into an ApiError with a readable message. */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch {
    throw new ApiError(0, 'The server could not be reached. Check that it is running.')
  }
  if (!response.ok) {
    let message = `The server answered with an error (${response.status}).`
    try {
      const body = await response.json()
      // FastAPI puts its message in "detail": text for our own errors, a list for
      // validation errors.
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg
    } catch {
      // The body was not JSON (for example the dev proxy's error page); keep the message above.
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as T
}

export function startSampleRun(file: string) {
  const form = new FormData()
  form.append('sample', file)
  return request<{ id: string }>('/api/runs', { method: 'POST', body: form })
}

export function startUploadRun(file: File) {
  const form = new FormData()
  form.append('file', file)
  return request<{ id: string }>('/api/runs', { method: 'POST', body: form })
}

export function resolveRun(id: string, action: 'approve' | 'reject', comment: string, poId?: string) {
  return request<RunDetail>(`/api/runs/${id}/resolve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, comment, po_id: poId ?? null }),
  })
}

export function resetDemo() {
  return request<{ status: string }>('/api/demo/reset', { method: 'POST' })
}
