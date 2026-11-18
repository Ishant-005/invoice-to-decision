// Screen 1: the dashboard. Summary tiles, the runs table with a decision filter, and the
// seeded history.

import { Plus } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'

import {
  DecisionBadge,
  EmptyState,
  ErrorBox,
  Loading,
  PageHeader,
  Panel,
  StateLabel,
  Tag,
} from '@/components/common'
import { Button } from '@/components/ui/button'
import type { Decision, RunList, RunSummary, Stats } from '@/lib/api'
import { day, inr, moment } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

type Filter = 'ALL' | Decision

export function Dashboard() {
  // While any run is still being processed, both calls repeat so the screen stays current.
  const runs = useApi<RunList>('/api/runs', (list) => list.runs.some((r) => r.state === 'processing'), 1500)
  const stats = useApi<Stats>('/api/stats', (s) => s.in_progress > 0, 1500)
  const [filter, setFilter] = useState<Filter>('ALL')

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Every invoice the process has handled, what it decided and why."
      />

      {stats.error ? (
        <ErrorBox message={stats.error} onRetry={stats.reload} />
      ) : (
        <StatTiles stats={stats.data} />
      )}

      <div className="mt-6">
        {runs.loading ? (
          <Panel>
            <Loading label="Loading runs…" />
          </Panel>
        ) : runs.error && !runs.data ? (
          <ErrorBox message={runs.error} onRetry={runs.reload} />
        ) : runs.data ? (
          <>
            <RunsTable runs={runs.data.runs} filter={filter} onFilter={setFilter} />
            <SeededHistory list={runs.data} />
          </>
        ) : null}
      </div>
    </>
  )
}

// --- Tiles -----------------------------------------------------------------------------

function StatTiles({ stats }: { stats: Stats | null }) {
  const s = stats
  const reviewed = s ? s.approved_by_reviewer + s.rejected_by_reviewer : 0
  return (
    <div className="grid grid-cols-5 gap-3">
      <Tile
        label="Invoices processed"
        value={s ? String(s.processed) : null}
        note={
          s
            ? [
                s.in_progress > 0 && `${s.in_progress} in progress`,
                s.failed > 0 && `${s.failed} failed, no decision`,
                `plus ${s.seeded_invoices} in seeded history`,
              ]
                .filter(Boolean)
                .join(' · ')
            : ''
        }
      />
      <Tile
        label="Auto-approved"
        value={s ? (s.auto_approved_percent === null ? '—' : `${s.auto_approved_percent}%`) : null}
        note={s ? (s.processed ? `${s.auto_approved} of ${s.processed} needed no person` : 'Nothing processed yet') : ''}
        tone="approve"
      />
      <Tile
        label="Awaiting review"
        value={s ? String(s.awaiting_review) : null}
        note={s ? (reviewed ? `${reviewed} already resolved by a reviewer` : 'Waiting for a person to decide') : ''}
        tone="review"
      />
      <Tile
        label="Rejected"
        value={s ? String(s.rejected) : null}
        note={
          s
            ? s.rejected_by_reviewer
              ? `plus ${s.rejected_by_reviewer} rejected by a reviewer`
              : 'Rejected by the process itself'
            : ''
        }
        tone="reject"
      />
      <Tile
        label="Value approved"
        value={s ? inr(s.value_approved_pretax) : null}
        note={s ? `before tax · ${inr(s.value_approved_gross)} including tax` : ''}
      />
    </div>
  )
}

function Tile({
  label,
  value,
  note,
  tone,
}: {
  label: string
  value: string | null
  note: string
  tone?: 'approve' | 'review' | 'reject'
}) {
  const bar = { approve: 'bg-approve', review: 'bg-review', reject: 'bg-reject' }
  return (
    <Panel className="relative overflow-hidden px-4 py-3.5">
      <span className={cn('absolute inset-y-0 left-0 w-[3px]', tone ? bar[tone] : 'bg-border')} />
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <p className="num mt-1.5 text-2xl font-semibold tracking-tight">
        {value ?? <span className="text-muted-foreground">…</span>}
      </p>
      <p className="mt-1 min-h-4 text-xs text-muted-foreground">{note}</p>
    </Panel>
  )
}

// --- Runs table ------------------------------------------------------------------------

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'ALL', label: 'All' },
  { key: 'APPROVE', label: 'Approve' },
  { key: 'REVIEW', label: 'Review' },
  { key: 'REJECT', label: 'Reject' },
]

function RunsTable({
  runs,
  filter,
  onFilter,
}: {
  runs: RunSummary[]
  filter: Filter
  onFilter: (filter: Filter) => void
}) {
  const navigate = useNavigate()
  const shown = filter === 'ALL' ? runs : runs.filter((run) => run.decision === filter)
  const count = (key: Filter) => (key === 'ALL' ? runs.length : runs.filter((r) => r.decision === key).length)

  return (
    <Panel>
      <div className="flex items-center justify-between border-b px-4 py-2.5">
        <h2 className="font-semibold">Runs</h2>
        <div className="flex items-center gap-1" role="group" aria-label="Filter by decision">
          {FILTERS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => onFilter(key)}
              aria-pressed={filter === key}
              className={cn(
                'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                filter === key
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground',
              )}
            >
              {label} <span className="num ml-0.5 opacity-70">{count(key)}</span>
            </button>
          ))}
        </div>
      </div>

      {runs.length === 0 ? (
        <EmptyState
          title="No invoices have been run yet"
          action={
            <Button asChild>
              <Link to="/new">
                <Plus /> New run
              </Link>
            </Button>
          }
        >
          Run one of the 13 sample invoices or upload a PDF. Each run appears here with its
          decision and the reason for it.
        </EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState title={`No runs with the decision ${filter.toLowerCase()}`}>
          Choose another filter to see the other runs.
        </EmptyState>
      ) : (
        <table className="w-full table-fixed text-left">
          <thead>
            <tr className="border-b text-xs text-muted-foreground [&>th]:px-3 [&>th]:py-2 [&>th]:font-medium">
              <th className="w-[100px] pl-4!">Time</th>
              <th className="w-[236px]">Vendor</th>
              <th className="w-[124px]">Invoice no.</th>
              <th className="w-[98px] text-right">Amount</th>
              <th className="w-[76px]">PO</th>
              <th className="w-[94px]">Decision</th>
              <th>Headline reason</th>
              <th className="w-[150px]">State</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((run) => (
              <tr
                key={run.id}
                onClick={() => navigate(`/runs/${run.id}`)}
                className="cursor-pointer border-b last:border-b-0 hover:bg-accent/50 [&>td]:px-3 [&>td]:py-2"
              >
                <td className="num pl-4! text-xs whitespace-nowrap text-muted-foreground">
                  {moment(run.created_at)}
                </td>
                <td className="truncate font-medium" title={run.vendor_name ?? run.file_name}>
                  <Link to={`/runs/${run.id}`} onClick={(event) => event.stopPropagation()}>
                    {run.vendor_name ?? <span className="text-muted-foreground">{run.file_name}</span>}
                  </Link>
                </td>
                <td className="num truncate">
                  {run.invoice_number ?? <Missing state={run.state} />}
                </td>
                <td className="num text-right">
                  {run.gross_amount ? (
                    inr(run.gross_amount)
                  ) : run.pretax_amount ? (
                    <span title="The total could not be read; this is the amount before tax">
                      {inr(run.pretax_amount)}
                      <span className="block font-sans text-[10px] text-muted-foreground">before tax</span>
                    </span>
                  ) : (
                    <Missing state={run.state} />
                  )}
                </td>
                <td className="num whitespace-nowrap">{run.po_id ?? <span className="text-muted-foreground">—</span>}</td>
                <td>{run.decision ? <DecisionBadge decision={run.decision} /> : <span className="text-muted-foreground">—</span>}</td>
                <td className="text-[13px] leading-snug text-foreground/80" title={run.headline ?? run.error_message ?? ''}>
                  <span className="line-clamp-2">
                  {run.state === 'processing'
                    ? 'Working through the six stages…'
                    : (reasonOnly(run.headline) ?? run.error_message)}
                  </span>
                </td>
                <td className="text-xs">
                  <StateLabel state={run.state} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  )
}

/** "Needs review: the invoice takes…" -> "The invoice takes…". The Decision column already
 *  says approve, review or reject, so the table shows only the reason. */
function reasonOnly(headline: string | null): string | null {
  if (!headline) return null
  if (!headline.includes(': ')) return headline
  const lead = headline.slice(0, headline.indexOf(': '))
  const reason = headline.slice(headline.indexOf(': ') + 2)
  // "Approved with 2 notes" keeps its notes: "With 2 notes: the invoice matches…".
  const notes = /with \d+ notes?/.exec(lead)
  const text = notes ? `${notes[0]}: ${reason}` : reason
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/** A value the document did not give. While a run is in progress it is simply not known yet. */
function Missing({ state }: { state: RunSummary['state'] }) {
  if (state === 'processing' || state === 'failed') return <span className="text-muted-foreground">—</span>
  return <span className="font-sans text-xs text-review italic">not found</span>
}

// --- Seeded history --------------------------------------------------------------------

function SeededHistory({ list }: { list: RunList }) {
  if (list.seeded_history.length === 0) return null
  return (
    <Panel className="mt-4">
      <div className="flex items-baseline gap-3 border-b px-4 py-2.5">
        <h2 className="font-semibold">Seeded history</h2>
        <p className="text-xs text-muted-foreground">
          Invoices approved before the demo starts. They were not run through the app, so they
          are not counted in the tiles above, but duplicate and balance checks see them.
        </p>
      </div>
      <table className="w-full table-fixed text-left">
        <tbody>
          {list.seeded_history.map((invoice) => (
            <tr key={invoice.file_name} className="border-b last:border-b-0 [&>td]:px-3 [&>td]:py-2">
              <td className="num w-[100px] pl-4! text-xs whitespace-nowrap text-muted-foreground">{day(invoice.invoice_date)}</td>
              <td className="w-[236px] truncate font-medium">{invoice.vendor_name}</td>
              <td className="num w-[124px]">{invoice.invoice_number}</td>
              <td className="num w-[98px] text-right">{inr(invoice.gross_amount)}</td>
              <td className="num w-[76px] whitespace-nowrap">
                <Link className="underline-offset-2 hover:underline" to={`/purchase-orders?po=${invoice.po_id}`}>
                  {invoice.po_id}
                </Link>
              </td>
              <td className="w-[94px] text-muted-foreground">—</td>
              <td className="truncate text-[13px] text-muted-foreground">
                <Tag className="mr-2">Seeded history</Tag>Approved before the demo started
              </td>
              <td className="w-[150px] text-xs">
                <StateLabel state="approved" />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}
