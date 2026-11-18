// The vertical timeline of the six stages. Each stage shows its state and real measured
// duration, and opens to show what it found.

import { Check, ChevronDown, Loader2, Minus, Sparkles, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'

import { Eyebrow, Tag } from '@/components/common'
import type {
  ExtractResult,
  Finding,
  MatchResult,
  ReceiveResult,
  RunDetail,
  Stage,
  StageName,
  ValidateResult,
} from '@/lib/api'
import { day, duration, fileSize, inr, quantity } from '@/lib/format'
import { cn } from '@/lib/utils'

import { BalanceBar } from './BalanceBar'
import { Checklist } from './Checklist'
import { summariseFindings, TONES, worstTone } from './findings'
import { STAGE_INFO } from './stages'

export function StageTimeline({
  run,
  stages,
}: {
  run: RunDetail
  stages: Stage[] // the stages as they should be shown now (see RunView for the pacing)
}) {
  // A stage the user has opened or closed by hand keeps that choice.
  const [chosen, setChosen] = useState<Partial<Record<StageName, boolean>>>({})

  return (
    <ol>
      {stages.map((stage, index) => {
        const open = chosen[stage.stage] ?? openByDefault(stage)
        const canOpen = stage.status === 'done' || stage.status === 'failed'
        const last = index === stages.length - 1
        return (
          <li key={stage.stage} className="relative flex gap-3">
            {/* The line that joins this stage to the next. */}
            {!last && <span className="absolute top-8 bottom-0 left-[13px] w-px bg-border" />}
            <StageMarker stage={stage} number={index + 1} />

            <div className={cn('mb-2.5 min-w-0 flex-1 rounded-lg border bg-card', stage.status === 'running' && 'border-primary/50')}>
              <button
                type="button"
                disabled={!canOpen}
                aria-expanded={open && canOpen}
                onClick={() => setChosen({ ...chosen, [stage.stage]: !open })}
                className="flex w-full items-center gap-3 px-3.5 py-2.5 text-left"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={cn('font-semibold', (stage.status === 'waiting' || stage.status === 'not_run') && 'text-muted-foreground')}>
                      {STAGE_INFO[stage.stage].name}
                    </span>
                    {stage.uses_ai ? (
                      <Tag className="border-primary/25 bg-accent text-accent-foreground">
                        <Sparkles className="size-3" /> AI model
                      </Tag>
                    ) : (
                      <Tag>Code</Tag>
                    )}
                  </div>
                  <p className="mt-0.5 truncate text-[13px] text-muted-foreground">
                    <StageSummary stage={stage} run={run} />
                  </p>
                </div>
                <StageTime stage={stage} />
                <ChevronDown
                  className={cn('size-4 shrink-0 text-muted-foreground transition-transform', open && canOpen && 'rotate-180', !canOpen && 'opacity-0')}
                />
              </button>

              {open && canOpen && (
                <div className="border-t px-3.5 py-3">
                  <StageBody stage={stage} run={run} />
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/** Stages with something to look at start open; the rest start closed. */
function openByDefault(stage: Stage): boolean {
  if (stage.status === 'failed') return true
  if (stage.status !== 'done') return false
  if (stage.findings.some((finding) => finding.status === 'fail' || finding.status === 'warn')) return true
  if (stage.stage === 'receive') return (stage.result as ReceiveResult).seen_before
  if (stage.stage === 'extract') {
    const result = stage.result as ExtractResult
    const record = result.record
    const keyFieldMissing = [record.vendor_name, record.invoice_number, record.invoice_date, record.total].some((v) => v === null)
    return keyFieldMissing || result.source !== 'live'
  }
  if (stage.stage === 'match') return (stage.result as MatchResult).po !== null
  return false
}

function StageMarker({ stage, number }: { stage: Stage; number: number }) {
  const base = 'relative z-10 mt-2.5 flex size-[27px] shrink-0 items-center justify-center rounded-full border text-xs font-semibold'
  if (stage.status === 'running')
    return (
      <span className={cn(base, 'border-primary bg-card text-primary')} aria-label="Running">
        <Loader2 className="size-3.5 animate-spin" />
      </span>
    )
  if (stage.status === 'done')
    return (
      <span className={cn(base, 'border-primary bg-primary text-primary-foreground')} aria-label="Done">
        <Check className="size-3.5" strokeWidth={3} />
      </span>
    )
  if (stage.status === 'failed')
    return (
      <span className={cn(base, 'border-reject bg-reject text-background')} aria-label="Failed">
        <X className="size-3.5" strokeWidth={3} />
      </span>
    )
  if (stage.status === 'not_run')
    return (
      <span className={cn(base, 'bg-muted text-muted-foreground')} aria-label="Not run">
        <Minus className="size-3.5" />
      </span>
    )
  return (
    <span className={cn(base, 'num bg-card text-muted-foreground')} aria-label="Waiting">
      {number}
    </span>
  )
}

/** The right-hand side of a stage's header: its state in a word and its measured time. */
function StageTime({ stage }: { stage: Stage }) {
  if (stage.status === 'running') return <RunningClock />
  if (stage.status === 'waiting') return <span className="text-xs text-muted-foreground">Waiting</span>
  if (stage.status === 'not_run') return <span className="text-xs text-muted-foreground">Not run</span>
  return (
    <span className="text-right">
      <span className="num block text-[13px] font-medium" title="Measured on the server">
        {duration(stage.duration_ms)}
      </span>
      <span className={cn('block text-[11px]', stage.status === 'failed' ? 'font-medium text-reject' : 'text-muted-foreground')}>
        {stage.status === 'failed' ? 'Failed' : 'Done'}
      </span>
    </span>
  )
}

/** Counts up while a stage is running, from the moment this page first saw it running. The
 *  figure shown once the stage has finished is the server's measurement, not this clock. */
function RunningClock() {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = window.setInterval(() => setSeconds((Date.now() - started) / 1000), 100)
    return () => window.clearInterval(timer)
  }, [])
  return (
    <span className="text-right">
      <span className="num block text-[13px] font-medium text-primary">{seconds.toFixed(1)} s</span>
      <span className="block text-[11px] font-medium text-primary">Running</span>
    </span>
  )
}

// --- One-line summaries ----------------------------------------------------------------

function StageSummary({ stage, run }: { stage: Stage; run: RunDetail }) {
  if (stage.status === 'waiting' || stage.status === 'not_run') return STAGE_INFO[stage.stage].does
  if (stage.status === 'running')
    return stage.stage === 'extract' ? 'The AI model is reading the document…' : STAGE_INFO[stage.stage].does
  if (stage.status === 'failed') return run.error_message ?? 'This stage failed.'

  switch (stage.stage) {
    case 'receive': {
      const r = stage.result as ReceiveResult
      return `PDF accepted · ${fileSize(r.size_bytes)} · ${r.page_count} page${r.page_count > 1 ? 's' : ''}${r.seen_before ? ' · this exact file was submitted before' : ''}`
    }
    case 'extract': {
      const r = stage.result as ExtractResult
      const missing = missingFields(r).length
      return (
        <>
          {capitalise(r.label)}
          {missing > 0 && <span className="font-medium text-review"> · {missing} field{missing > 1 ? 's' : ''} not found on the document</span>}
        </>
      )
    }
    case 'decide':
      return run.decision_detail?.headline ?? ''
    default: {
      const tone = worstTone(stage.findings)
      return <span className={cn(tone !== 'pass' && 'font-medium', tone !== 'pass' && TONES[tone].text)}>{summariseFindings(stage.findings)}</span>
    }
  }
}

function capitalise(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

// --- What each stage found -------------------------------------------------------------

function StageBody({ stage, run }: { stage: Stage; run: RunDetail }) {
  if (stage.status === 'failed')
    return (
      <p className="text-reject">
        {run.error_message} <span className="text-muted-foreground">No decision was made and no balance was changed.</span>
      </p>
    )
  switch (stage.stage) {
    case 'receive':
      return <ReceiveBody result={stage.result as ReceiveResult} />
    case 'extract':
      return <ExtractBody result={stage.result as ExtractResult} />
    case 'validate':
      return <ValidateBody result={stage.result as ValidateResult} findings={stage.findings} />
    case 'match':
      return <MatchBody result={stage.result as MatchResult} findings={stage.findings} run={run} />
    case 'rules':
      return <Checklist findings={stage.findings} />
    case 'decide':
      return <DecideBody run={run} />
  }
}

function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[150px_1fr] gap-x-4 gap-y-1.5">
      {rows.map(([label, value]) => (
        <div key={label} className="contents">
          <dt className="text-muted-foreground">{label}</dt>
          <dd className="min-w-0">{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function ReceiveBody({ result }: { result: ReceiveResult }) {
  return (
    <Facts
      rows={[
        ['File', result.file_name],
        ['Type and size', `PDF · ${fileSize(result.size_bytes)} (limit 10 MB)`],
        ['Pages', `${result.page_count} (limit 5)`],
        ['Fingerprint (SHA-256)', <span key="hash" className="code break-all">{result.file_hash}</span>],
        [
          'Seen before',
          result.seen_before ? (
            <span className="font-medium text-review">Yes. {result.note}</span>
          ) : (
            'No, this file has not been submitted before'
          ),
        ],
      ]}
    />
  )
}

const NOT_FOUND = (
  <span className="rounded border border-review-line bg-review-soft px-1.5 py-px text-xs font-medium text-review">
    not found on the document
  </span>
)

/** The fields the reader came back without. */
function missingFields(result: ExtractResult): string[] {
  const r = result.record
  const fields: [string, unknown][] = [
    ['vendor name', r.vendor_name],
    ['invoice number', r.invoice_number],
    ['invoice date', r.invoice_date],
    ['PO reference', r.po_reference],
    ['total', r.total],
  ]
  return fields.filter(([, value]) => value === null).map(([name]) => name)
}

function ExtractBody({ result }: { result: ExtractResult }) {
  const r = result.record
  const quote = (field: string) => r.evidence?.[field] || null
  // Field, the value read, and the words on the page it was read from (kept for five fields).
  const rows: [string, React.ReactNode | null, string | null][] = [
    ['Document type', capitalise(r.document_type.replace('_', ' ')), null],
    ['Vendor name', r.vendor_name, quote('vendor_name')],
    ['Vendor GSTIN', r.vendor_tax_id && <span className="num">{r.vendor_tax_id}</span>, null],
    ['Invoice number', r.invoice_number && <span className="num">{r.invoice_number}</span>, quote('invoice_number')],
    [
      'Invoice date',
      r.invoice_date && (
        <>
          {day(r.invoice_date)}
          {r.date_is_ambiguous && <span className="ml-2 text-xs font-medium text-review">day and month could be either way round</span>}
        </>
      ),
      quote('invoice_date'),
    ],
    ['PO reference', r.po_reference && <span className="num">{r.po_reference}</span>, quote('po_reference')],
    ['Currency', r.currency, null],
    ['Subtotal, before tax', r.subtotal && <span className="num">{inr(r.subtotal)}</span>, null],
    [
      'Tax',
      r.tax_amount ? (
        <span className="num">
          {inr(r.tax_amount)}
          {r.tax_rate_percent && <span className="text-muted-foreground"> at {quantity(r.tax_rate_percent)}%</span>}
        </span>
      ) : r.tax_rate_percent ? (
        <span>
          <span className="num">{quantity(r.tax_rate_percent)}%</span>
          <span className="text-muted-foreground"> stated, amount not printed</span>
        </span>
      ) : null,
      null,
    ],
    [
      'Total',
      r.total && (
        <span className="num font-semibold">
          {inr(r.total)}
          {r.amounts_tax_inclusive && <span className="ml-2 font-sans text-xs font-normal text-muted-foreground">stated as including tax</span>}
        </span>
      ),
      quote('total'),
    ],
  ]

  return (
    <div className="space-y-4">
      <table className="w-full text-left">
        <thead>
          <tr className="text-[11px] tracking-wider text-muted-foreground uppercase [&>th]:pb-1.5 [&>th]:font-semibold">
            <th className="w-[150px]">Field</th>
            <th>Value read</th>
            <th className="w-[38%]">Quoted from the page</th>
          </tr>
        </thead>
        <tbody className="divide-y border-y">
          {rows.map(([label, value, evidence]) => (
            <tr key={label} className={cn('[&>td]:py-1.5 [&>td]:pr-3', !value && 'bg-review-soft/50')}>
              <td className="text-muted-foreground">{label}</td>
              <td>{value || NOT_FOUND}</td>
              <td className="code text-muted-foreground">{evidence && <>“{evidence}”</>}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <div>
        <Eyebrow className="mb-1.5">Line items</Eyebrow>
        {r.line_items.length === 0 ? (
          <p className="text-muted-foreground">None printed: the invoice gives one bundled amount.</p>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs text-muted-foreground [&>th]:pb-1 [&>th]:font-medium">
                <th>Description</th>
                <th className="w-20 text-right">Quantity</th>
                <th className="w-28 text-right">Unit price</th>
                <th className="w-28 text-right">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y border-y">
              {r.line_items.map((line, index) => (
                <tr key={index} className="[&>td]:py-1.5">
                  <td>{line.description ?? NOT_FOUND}</td>
                  <td className="num text-right">{quantity(line.quantity)}</td>
                  <td className="num text-right">{inr(line.unit_price)}</td>
                  <td className="num text-right">{inr(line.amount)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {r.notes && (
        <div className="rounded-md border bg-muted/60 px-3 py-2">
          <Eyebrow>The reader's own note</Eyebrow>
          <p className="mt-0.5">{r.notes}</p>
          <p className="mt-1 text-xs text-muted-foreground">Shown for the reviewer. No check or decision uses this note.</p>
        </div>
      )}

      {result.live_error && (
        <p className="text-review">
          The live call failed ({result.live_error}), so the reading saved earlier for this exact file was used.
        </p>
      )}

      <p className="text-xs text-muted-foreground">
        {capitalise(result.label)}
        {result.model && <> · model <span className="code">{result.model}</span></>}
        {result.input_tokens !== null && result.output_tokens !== null && result.source === 'live' && (
          <> · <span className="num">{result.input_tokens.toLocaleString('en-IN')}</span> tokens in, <span className="num">{result.output_tokens.toLocaleString('en-IN')}</span> out</>
        )}
        . The model only reads; it is told to return nothing for a field that is not printed, and
        never to calculate or guess.
      </p>
    </div>
  )
}

const PRETAX_SOURCES: Record<string, string> = {
  printed_subtotal: 'the printed subtotal',
  derived_from_inclusive_total: 'worked out from the tax-inclusive total and the stated rate',
}

function ValidateBody({ result, findings }: { result: ValidateResult; findings: Finding[] }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 rounded-md bg-muted/60 px-3 py-2">
        <div>
          <Eyebrow>Amount before tax</Eyebrow>
          <p className="num mt-0.5 text-[15px] font-semibold">{result.pretax_amount ? inr(result.pretax_amount) : 'could not be worked out'}</p>
          <p className="text-xs text-muted-foreground">
            {result.pretax_amount && (PRETAX_SOURCES[result.pretax_source] ?? result.pretax_source.replaceAll('_', ' '))}. Compared with the purchase order.
          </p>
        </div>
        <div>
          <Eyebrow>Total including tax</Eyebrow>
          <p className="num mt-0.5 text-[15px] font-semibold">{result.gross_amount ? inr(result.gross_amount) : 'not readable'}</p>
          <p className="text-xs text-muted-foreground">The amount payable, as printed.</p>
        </div>
      </div>
      <Checklist findings={findings} />
    </div>
  )
}

const VENDOR_MATCH: Record<MatchResult['vendor_match'], string> = {
  tax_id: 'Confirmed: the GSTIN matches the vendor master exactly',
  name: 'Confirmed: the name matches the vendor master once suffixes such as Pvt Ltd are removed',
  suggested: 'Suggested only: the name is similar to one in the vendor master',
  none: 'Not found in the vendor master',
}

const PO_MATCH: Record<MatchResult['po_match_type'], string> = {
  explicit_verified: 'Confirmed: quoted on the invoice and belongs to this vendor',
  explicit_conflict: 'Conflict: quoted on the invoice but belongs to another vendor',
  not_found: 'The number quoted on the invoice is not a known purchase order',
  implied_single: 'Suggested: none is quoted, and this is the only one that fits',
  implied_multiple: 'None is quoted, and several could fit',
  none: 'None is quoted and none fits',
}

function MatchBody({ result, findings, run }: { result: MatchResult; findings: Finding[]; run: RunDetail }) {
  const po = result.po
  const validate = run.stages.find((stage) => stage.stage === 'validate')?.result as ValidateResult | null
  const vendorOk = result.vendor_match === 'tax_id' || result.vendor_match === 'name'
  const poOk = result.po_match_type === 'explicit_verified'
  const booked = run.state === 'approved' || run.state === 'approved_by_reviewer'

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-md border px-3 py-2.5">
          <Eyebrow>Vendor</Eyebrow>
          <p className="mt-1 font-semibold">
            {result.vendor_name ?? 'No vendor'}
            {result.vendor_id && <span className="num ml-2 text-xs font-normal text-muted-foreground">{result.vendor_id}</span>}
          </p>
          <p className={cn('mt-0.5 text-[13px]', vendorOk ? 'text-approve' : result.vendor_match === 'none' ? 'text-reject' : 'text-review')}>
            {VENDOR_MATCH[result.vendor_match]}
          </p>
        </div>
        <div className="rounded-md border px-3 py-2.5">
          <Eyebrow>Purchase order</Eyebrow>
          <p className="mt-1 font-semibold">
            {result.po_id ? (
              <Link className="num underline-offset-2 hover:underline" to={`/purchase-orders?po=${result.po_id}`}>
                {result.po_id}
              </Link>
            ) : (
              'No purchase order'
            )}
            {po && <span className="ml-2 text-xs font-normal text-muted-foreground">{po.status}</span>}
          </p>
          <p className={cn('mt-0.5 text-[13px]', poOk ? 'text-approve' : 'text-review')}>{PO_MATCH[result.po_match_type]}</p>
        </div>
      </div>

      {po && (
        <div>
          <Eyebrow className="mb-1">Purchase order balance</Eyebrow>
          <BalanceBar poId={po.po_id} value={po.value} billedBefore={po.billed_to_date} thisInvoice={validate?.pretax_amount ?? null} booked={booked} />
          {po.earlier_invoices.length > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              Earlier invoices against {po.po_id}:{' '}
              {po.earlier_invoices.map((invoice, index) => (
                <span key={index}>
                  {index > 0 && '; '}
                  <span className="num text-foreground">{invoice.invoice_number ?? 'no number'}</span> ({day(invoice.invoice_date)},{' '}
                  <span className="num">{inr(invoice.pretax_amount)}</span>, {invoice.state.replace('_', ' ')})
                </span>
              ))}
            </p>
          )}
        </div>
      )}

      {result.line_pairs.length > 0 && (
        <div>
          <Eyebrow className="mb-1.5">Invoice lines against the purchase order</Eyebrow>
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs text-muted-foreground [&>th]:pb-1 [&>th]:font-medium">
                <th className="w-[46%]">Invoice line</th>
                <th>Purchase order line</th>
                <th className="w-28 text-right">Wording match</th>
              </tr>
            </thead>
            <tbody className="divide-y border-y">
              {result.line_pairs.map((pair) => (
                <tr key={pair.invoice_line} className="[&>td]:py-1.5 [&>td]:pr-3">
                  <td>{pair.description}</td>
                  <td>{pair.po_description ?? <span className="font-medium text-review">Not on the purchase order</span>}</td>
                  {/* The score says how alike the two descriptions are, so it is shown only when
                      a purchase order line was matched. */}
                  <td className="num text-right whitespace-nowrap text-muted-foreground">
                    {pair.po_line_no !== null ? `${pair.score.toFixed(0)} / 100` : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Checklist findings={findings} />
    </div>
  )
}

function DecideBody({ run }: { run: RunDetail }) {
  const detail = run.decision_detail
  if (!detail) return null
  const reviews = detail.reasons.filter((reason) => reason.severity === 'review').length
  const rejects = detail.reasons.filter((reason) => reason.severity === 'reject').length
  return (
    <div className="space-y-2">
      <p>
        The decision is the most serious outcome among all the findings:{' '}
        <span className="num">{rejects}</span> call for a rejection, <span className="num">{reviews}</span> call for a
        review, so the decision is <span className="font-semibold">{detail.decision}</span>.
      </p>
      <p className="text-muted-foreground">
        Every sentence in the banner above is put together by code from the checks' own results. No AI model writes
        or rewrites the explanation.
      </p>
    </div>
  )
}
