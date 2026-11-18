// For a suspected duplicate: this invoice and the earlier one side by side, field by field.

import { Equal, EqualNot } from 'lucide-react'
import { Link } from 'react-router'

import { ErrorBox, Eyebrow, Loading, Panel, Tag } from '@/components/common'
import type { DuplicateLink, ExtractResult, InvoiceDetail, InvoiceRecord, RunDetail } from '@/lib/api'
import { day, inr, quantity, toPaise } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

export function DuplicateCompare({ run, link }: { run: RunDetail; link: DuplicateLink }) {
  const earlier = useApi<InvoiceDetail>(link.invoice_id !== null ? `/api/invoices/${link.invoice_id}` : null)
  const mine = (run.stages.find((stage) => stage.stage === 'extract')?.result as ExtractResult | null)?.record

  return (
    <Panel>
      <div className="flex items-center gap-3 border-b px-4 py-2.5">
        <h2 className="font-semibold">Side by side with the earlier invoice</h2>
        <Tag className={link.kind === 'exact' ? 'border-reject-line bg-reject-soft text-reject' : 'border-review-line bg-review-soft text-review'}>
          {link.kind === 'exact' ? 'Exact duplicate' : 'Probable duplicate'}
        </Tag>
        <p className="ml-auto text-xs text-muted-foreground">Found by the Rules stage by comparing vendor, total, date and invoice number.</p>
      </div>

      {link.invoice_id === null ? (
        <p className="p-4 text-muted-foreground">{link.reason}</p>
      ) : earlier.loading ? (
        <Loading label="Loading the earlier invoice…" />
      ) : earlier.error || !earlier.data || !mine ? (
        <div className="p-4">
          <ErrorBox message={earlier.error ?? 'The earlier invoice could not be shown.'} onRetry={earlier.reload} />
        </div>
      ) : (
        <div className="grid grid-cols-[280px_280px_1fr] gap-5 p-4">
          <PageThumb label="This invoice" caption={run.file_name} src={run.pages[0]} />
          <PageThumb label="Earlier invoice" caption={earlier.data.file_name} src={earlier.data.pages[0]} />
          <FieldComparison mine={mine} earlier={earlier.data} />
        </div>
      )}
    </Panel>
  )
}

function PageThumb({ label, caption, src }: { label: string; caption: string; src: string | undefined }) {
  return (
    <figure>
      <Eyebrow className="mb-1.5">{label}</Eyebrow>
      {src ? (
        <a href={src} target="_blank" rel="noreferrer" title="Open the page at full size">
          <img src={src} alt={`${label}: first page of ${caption}`} className="w-full rounded border bg-white" />
        </a>
      ) : (
        <div className="flex aspect-[1/1.414] items-center justify-center rounded border bg-muted text-xs text-muted-foreground">
          No page image
        </div>
      )}
      <figcaption className="code mt-1 truncate text-[11px] text-muted-foreground">{caption}</figcaption>
    </figure>
  )
}

function FieldComparison({ mine, earlier }: { mine: InvoiceRecord; earlier: InvoiceDetail }) {
  const theirs = earlier.record
  const sameMoney = (a: string | null | undefined, b: string | null | undefined) => Boolean(a && b && toPaise(a) === toPaise(b))
  const line = (record: InvoiceRecord | null) => {
    const first = record?.line_items[0]
    if (!first) return null
    return `${quantity(first.quantity)} × ${first.description} at ${inr(first.unit_price)}`
  }

  // Label, this invoice's value, the earlier invoice's value, and whether they are the same.
  const rows: [string, string | null, string | null, boolean][] = [
    ['Invoice number', mine.invoice_number, earlier.invoice_number, mine.invoice_number === earlier.invoice_number],
    ['Invoice date', mine.invoice_date && day(mine.invoice_date), earlier.invoice_date && day(earlier.invoice_date), mine.invoice_date === earlier.invoice_date],
    ['Vendor', mine.vendor_name, earlier.vendor_name, mine.vendor_name?.toLowerCase() === earlier.vendor_name?.toLowerCase()],
    ['PO quoted', mine.po_reference, theirs?.po_reference ?? earlier.po_id, mine.po_reference === (theirs?.po_reference ?? earlier.po_id)],
    ['First line', line(mine), line(theirs), line(mine) !== null && line(mine)?.toLowerCase() === line(theirs)?.toLowerCase()],
    ['Before tax', mine.subtotal && inr(mine.subtotal), earlier.pretax_amount && inr(earlier.pretax_amount), sameMoney(mine.subtotal, earlier.pretax_amount)],
    ['Total including tax', mine.total && inr(mine.total), earlier.gross_amount && inr(earlier.gross_amount), sameMoney(mine.total, earlier.gross_amount)],
  ]
  const sameCount = rows.filter((row) => row[3]).length

  return (
    <div className="min-w-0">
      <table className="w-full table-fixed text-left">
        <thead>
          <tr className="text-[11px] tracking-wider text-muted-foreground uppercase [&>th]:pb-1.5 [&>th]:font-semibold">
            <th className="w-[130px]">Field</th>
            <th>This invoice</th>
            <th>Earlier invoice</th>
            <th className="w-[92px]"></th>
          </tr>
        </thead>
        <tbody className="divide-y border-y">
          {rows.map(([label, a, b, same]) => (
            <tr key={label} className={cn('[&>td]:py-2 [&>td]:pr-3', !same && 'bg-review-soft/60')}>
              <td className="text-muted-foreground">{label}</td>
              <td className="num break-words">{a ?? <span className="font-sans text-muted-foreground italic">not found</span>}</td>
              <td className="num break-words">{b ?? <span className="font-sans text-muted-foreground italic">not found</span>}</td>
              <td>
                {same ? (
                  <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                    <Equal className="size-3.5" /> Same
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs font-semibold text-review">
                    <EqualNot className="size-3.5" /> Different
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3">
        <span className="font-semibold">
          {sameCount} of {rows.length} fields are the same.
        </span>{' '}
        The earlier invoice is{' '}
        <span className="font-medium">{earlier.state.replace('_', ' ')}</span>
        {earlier.is_seeded ? (
          <> (seeded history, approved before the demo).</>
        ) : earlier.run_id ? (
          <>
            .{' '}
            <Link className="font-medium text-primary underline-offset-2 hover:underline" to={`/runs/${earlier.run_id}`}>
              Open its run
            </Link>
          </>
        ) : (
          '.'
        )}
      </p>
      {earlier.gross_amount && (
        <p className="mt-1 text-muted-foreground">
          If this is the same bill and both are paid, <span className="num text-foreground">{inr(earlier.gross_amount)}</span> is paid twice.
        </p>
      )}
    </div>
  )
}
