// Screen 4: the purchase orders, each with its value, billed amount, remaining balance and
// the invoices recorded against it.

import { ChevronRight, Plus } from 'lucide-react'
import { Fragment, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import { AddPurchaseOrder } from '@/components/AddPurchaseOrder'
import { EmptyState, ErrorBox, Eyebrow, Loading, PageHeader, Panel, Tag } from '@/components/common'
import { Button } from '@/components/ui/button'
import type { PurchaseOrder } from '@/lib/api'
import { day, inr, quantity, share } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

export function PurchaseOrders() {
  const orders = useApi<PurchaseOrder[]>('/api/purchase-orders')
  const [params] = useSearchParams()
  // A link such as /purchase-orders?po=PO-2260 arrives with that PO already open.
  const [open, setOpen] = useState<string[]>(params.get('po') ? [params.get('po') as string] : [])
  const [adding, setAdding] = useState(false)
  const toggle = (id: string) => setOpen(open.includes(id) ? open.filter((other) => other !== id) : [...open, id])

  return (
    <>
      <PageHeader
        title="Purchase orders"
        description="What the company agreed to buy. All amounts are before tax. Billed goes up only when an invoice is approved, by the process or by a reviewer."
        actions={
          !adding && orders.data ? (
            <Button onClick={() => setAdding(true)}>
              <Plus /> Add purchase order
            </Button>
          ) : null
        }
      />
      {adding && orders.data && (
        <AddPurchaseOrder
          orders={orders.data}
          onCancel={() => setAdding(false)}
          onAdded={(po) => {
            // Show the new PO in the table straight away, opened, in PO-number order.
            orders.setData([...(orders.data ?? []), po].sort((a, b) => (a.id < b.id ? -1 : 1)))
            setOpen([po.id])
            setAdding(false)
          }}
        />
      )}
      {orders.loading ? (
        <Panel>
          <Loading label="Loading purchase orders…" />
        </Panel>
      ) : orders.error ? (
        <ErrorBox message={orders.error} onRetry={orders.reload} />
      ) : !orders.data || orders.data.length === 0 ? (
        <Panel>
          <EmptyState title="There are no purchase orders">Reset the demo data to load the seed purchase orders.</EmptyState>
        </Panel>
      ) : (
        <Panel>
          <table className="w-full table-fixed text-left">
            <thead>
              <tr className="border-b text-xs text-muted-foreground [&>th]:px-3 [&>th]:py-2 [&>th]:font-medium">
                <th className="w-9"></th>
                <th className="w-[84px]">PO</th>
                <th>Vendor</th>
                <th className="w-[112px]">Dated</th>
                <th className="w-[112px] text-right">Value</th>
                <th className="w-[112px] text-right">Billed</th>
                <th className="w-[112px] text-right">Remaining</th>
                <th className="w-[190px]">Billed so far</th>
                <th className="w-[96px]">Invoices</th>
              </tr>
            </thead>
            <tbody>
              {orders.data.map((po) => {
                const isOpen = open.includes(po.id)
                const over = po.remaining.startsWith('-')
                return (
                  <Fragment key={po.id}>
                    <tr
                      onClick={() => toggle(po.id)}
                      className={cn('cursor-pointer border-b hover:bg-accent/50 [&>td]:px-3 [&>td]:py-2', isOpen && 'bg-accent/40')}
                    >
                      <td>
                        <button type="button" aria-expanded={isOpen} aria-label={`Show the detail of ${po.id}`} className="flex">
                          <ChevronRight className={cn('size-4 text-muted-foreground transition-transform', isOpen && 'rotate-90')} />
                        </button>
                      </td>
                      <td className="num font-semibold">{po.id}</td>
                      <td className="truncate">
                        {po.vendor_name} <span className="num ml-1 text-xs text-muted-foreground">{po.vendor_id}</span>
                      </td>
                      <td className="whitespace-nowrap text-muted-foreground">{day(po.po_date)}</td>
                      <td className="num text-right">{inr(po.value)}</td>
                      <td className="num text-right">{inr(po.billed_to_date)}</td>
                      <td className={cn('num text-right font-medium', over && 'text-review')}>{inr(po.remaining)}</td>
                      <td>
                        <div className="flex items-center gap-2">
                          <div className="h-2 flex-1 overflow-hidden rounded-full border bg-muted">
                            <div className={cn('h-full', over ? 'bg-review' : 'bg-primary')} style={{ width: `${share(po.billed_to_date, po.value) * 100}%` }} />
                          </div>
                          <span className="w-[74px] text-[11px] whitespace-nowrap text-muted-foreground">
                            {over ? 'over value' : po.remaining === po.value ? 'nothing billed' : toZero(po.remaining) ? 'fully billed' : 'part billed'}
                          </span>
                        </div>
                      </td>
                      <td className="num text-muted-foreground">{po.invoices.length || '—'}</td>
                    </tr>
                    {isOpen && (
                      <tr className="border-b bg-muted/40">
                        <td></td>
                        <td colSpan={8} className="px-3 py-3.5">
                          <PODetail po={po} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </Panel>
      )}
    </>
  )
}

function toZero(amount: string) {
  return /^0+(\.0+)?$/.test(amount)
}

const INVOICE_STATES: Record<string, { label: string; classes: string }> = {
  approved: { label: 'Approved, counted in billed', classes: 'text-approve' },
  awaiting_review: { label: 'Awaiting review, not counted', classes: 'text-review' },
  rejected: { label: 'Rejected, not counted', classes: 'text-reject' },
}

function PODetail({ po }: { po: PurchaseOrder }) {
  return (
    <div className="grid grid-cols-[2fr_3fr] gap-8">
      <div>
        <Eyebrow className="mb-1.5">What was ordered</Eyebrow>
        <table className="w-full text-left">
          <thead>
            <tr className="text-xs text-muted-foreground [&>th]:pb-1 [&>th]:font-medium">
              <th>Line</th>
              <th className="w-16 text-right">Qty</th>
              <th className="w-24 text-right">Unit price</th>
              <th className="w-24 text-right">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y border-y">
            {po.lines.map((line) => (
              <tr key={line.line_no} className="[&>td]:py-1.5">
                <td>{line.description}</td>
                <td className="num text-right">{quantity(line.quantity)}</td>
                <td className="num text-right">{inr(line.unit_price)}</td>
                <td className="num text-right">{inr(line.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1.5 text-xs text-muted-foreground">Status: {po.status}</p>
      </div>

      <div>
        <Eyebrow className="mb-1.5">Invoices against {po.id}</Eyebrow>
        {po.invoices.length === 0 ? (
          <p className="text-muted-foreground">No invoice has been recorded against this purchase order yet.</p>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs text-muted-foreground [&>th]:pb-1 [&>th]:font-medium">
                <th>Invoice no.</th>
                <th>Dated</th>
                <th className="text-right">Before tax</th>
                <th className="pl-5">State</th>
                <th></th>
              </tr>
            </thead>
            <tbody className="divide-y border-y">
              {po.invoices.map((invoice, index) => {
                const state = INVOICE_STATES[invoice.state]
                return (
                  <tr key={index} className="[&>td]:py-1.5">
                    <td className="num">{invoice.invoice_number ?? <span className="font-sans text-review italic">not found</span>}</td>
                    <td className="text-muted-foreground">{day(invoice.invoice_date)}</td>
                    <td className="num text-right">{inr(invoice.pretax_amount)}</td>
                    <td className={cn('pl-5 text-[13px] font-medium', state?.classes)}>{state?.label ?? invoice.state}</td>
                    <td className="text-right">
                      {invoice.run_id ? (
                        <Link className="text-[13px] font-medium text-primary underline-offset-2 hover:underline" to={`/runs/${invoice.run_id}`}>
                          Open run
                        </Link>
                      ) : (
                        <Tag>Seeded history</Tag>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
