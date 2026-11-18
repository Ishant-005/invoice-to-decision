// The purchase order's balance as a bar: what was billed before, what this invoice adds,
// and what is left (or how far over it goes).

import type { Money } from '@/lib/api'
import { fromPaise, inr, share, toPaise } from '@/lib/format'
import { cn } from '@/lib/utils'

export function BalanceBar({
  poId,
  value,
  billedBefore,
  thisInvoice,
  booked,
}: {
  poId: string
  value: Money // the PO's value, before tax
  billedBefore: Money // billed against the PO before this invoice
  thisInvoice: Money | null // this invoice before tax; null if it could not be worked out
  booked: boolean // true once this invoice has been added to the PO (it was approved)
}) {
  // Exact arithmetic in whole paise.
  const after = toPaise(billedBefore) + (thisInvoice ? toPaise(thisInvoice) : 0n)
  const remaining = toPaise(value) - after
  const over = remaining < 0n
  const overBy = fromPaise(-remaining)

  // The bar is as long as the larger of the PO value and the billed total, so an overage
  // sticks out past the "PO value" marker. Widths are for drawing only.
  const scale = fromPaise(over ? after : toPaise(value))
  const pct = (part: string) => `${share(part, scale) * 100}%`
  const withinPO = thisInvoice ? fromPaise(over ? toPaise(value) - toPaise(billedBefore) : toPaise(thisInvoice)) : '0'

  return (
    <div>
      <div className="relative pt-5">
        {over && (
          <div className="absolute top-0 flex -translate-x-full flex-col items-end" style={{ left: pct(value) }}>
            <span className="pr-1 text-[10px] leading-none font-medium whitespace-nowrap text-muted-foreground">
              PO value {inr(value)}
            </span>
          </div>
        )}
        <div className="relative flex h-5 overflow-hidden rounded border bg-muted">
          <div className="bg-foreground/45" style={{ width: pct(billedBefore) }} title={`Billed before: ${inr(billedBefore)}`} />
          {thisInvoice && (
            <div className="bg-primary" style={{ width: pct(withinPO) }} title={`This invoice: ${inr(thisInvoice)}`} />
          )}
          {over && (
            <div
              className="bg-review [background-image:repeating-linear-gradient(135deg,transparent_0_4px,var(--hatch)_4px_8px)]"
              style={{ width: pct(overBy) }}
              title={`Over the PO value by ${inr(overBy)}`}
            />
          )}
        </div>
        {over && <div className="absolute top-3 bottom-[-4px] w-px bg-foreground" style={{ left: pct(value) }} />}
      </div>

      <dl className="mt-3 grid grid-cols-4 gap-3">
        <Figure label={`${poId} value`} amount={inr(value)} />
        <Figure label="Billed before" amount={inr(billedBefore)} swatch="bg-foreground/45" />
        <Figure
          label="This invoice"
          amount={thisInvoice ? inr(thisInvoice) : 'not known'}
          swatch="bg-primary"
          note={thisInvoice ? (booked ? 'added to the PO' : 'not added unless approved') : undefined}
        />
        {over ? (
          <Figure label="Over the PO value by" amount={inr(overBy)} swatch="bg-review" tone="text-review" />
        ) : (
          <Figure label={thisInvoice ? 'Remaining after' : 'Remaining'} amount={inr(fromPaise(remaining))} swatch="bg-muted border" />
        )}
      </dl>
      <p className="mt-2 text-[11px] text-muted-foreground">All figures before tax, because purchase order values are before tax.</p>
    </div>
  )
}

function Figure({
  label,
  amount,
  swatch,
  note,
  tone,
}: {
  label: string
  amount: string
  swatch?: string
  note?: string
  tone?: string
}) {
  return (
    <div>
      <dt className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        {swatch && <span className={cn('size-2 rounded-[2px]', swatch)} />}
        {label}
      </dt>
      <dd className={cn('num mt-0.5 text-[15px] font-semibold', tone)}>{amount}</dd>
      {note && <dd className="text-[11px] text-muted-foreground">{note}</dd>}
    </div>
  )
}
