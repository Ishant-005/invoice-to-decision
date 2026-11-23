// The "Add purchase order" form on the Purchase orders screen. Plain code, no AI: the line
// amounts and the PO value are worked out as the person types (see lib/newPo.ts), and the
// backend checks everything again when the form is saved.

import { Plus, Trash2 } from 'lucide-react'
import { type FormEvent, type ReactNode, useState } from 'react'

import { Panel } from '@/components/common'
import { Button } from '@/components/ui/button'
import type { PurchaseOrder } from '@/lib/api'
import { fromPaise, inr } from '@/lib/format'
import {
  addPurchaseOrder,
  checkNewPo,
  EMPTY_LINE,
  type Errors,
  lineAmountPaise,
  type NewLine,
  type NewPO,
  nextPoNumber,
  todayInIndia,
  valuePaise,
} from '@/lib/newPo'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

interface Vendor {
  id: string
  name: string
  status: string
}

const INPUT =
  'h-8 w-full rounded-md border border-input bg-background px-2.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 aria-invalid:border-reject'

export function AddPurchaseOrder({
  orders,
  onAdded,
  onCancel,
}: {
  orders: PurchaseOrder[]
  onAdded: (po: PurchaseOrder) => void
  onCancel: () => void
}) {
  const vendors = useApi<Vendor[]>('/api/vendors')
  const today = todayInIndia()
  const [po, setPo] = useState<NewPO>(() => ({
    vendor_id: '',
    po_number: nextPoNumber(orders),
    po_date: today,
    lines: [{ ...EMPTY_LINE }],
  }))
  // A message appears under a field once the person has left it, or after they press Save.
  const [touched, setTouched] = useState<string[]>([])
  const [triedToSave, setTriedToSave] = useState(false)
  const [serverErrors, setServerErrors] = useState<Errors>({})
  const [failure, setFailure] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const errors = { ...serverErrors, ...checkNewPo(po, orders, (vendors.data ?? []).map((v) => v.id), today) }
  const errorFor = (field: string) => (triedToSave || touched.includes(field) ? errors[field] : undefined)
  const touch = (field: string) => setTouched((fields) => (fields.includes(field) ? fields : [...fields, field]))

  function change(changes: Partial<NewPO>) {
    setPo({ ...po, ...changes })
    setServerErrors({})
    setFailure(null)
  }
  const changeLine = (index: number, changes: Partial<NewLine>) =>
    change({ lines: po.lines.map((line, i) => (i === index ? { ...line, ...changes } : line)) })

  function removeLine(index: number) {
    change({ lines: po.lines.filter((_, i) => i !== index) })
    // The lines after this one move up, so forget which of their fields had been visited.
    setTouched((fields) => fields.filter((field) => !field.startsWith('lines.')))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setTriedToSave(true)
    if (Object.keys(checkNewPo(po, orders, (vendors.data ?? []).map((v) => v.id), today)).length > 0) return
    setSaving(true)
    const answer = await addPurchaseOrder(po)
    setSaving(false)
    if ('po' in answer) onAdded(answer.po)
    else {
      setServerErrors(answer.errors)
      setFailure(answer.message)
    }
  }

  return (
    <Panel className="mb-4">
      <form onSubmit={save} noValidate data-testid="add-po-form">
        <div className="border-b px-4 py-2.5">
          <h2 className="font-semibold">Add purchase order</h2>
          <p className="text-xs text-muted-foreground">
            It starts open with nothing billed. Amounts are before tax. Reset demo data removes it again.
          </p>
        </div>

        <div className="grid grid-cols-[2fr_1fr_1fr] gap-4 px-4 pt-4">
          <Field label="Vendor" id="po-vendor" error={errorFor('vendor_id')}>
            <select
              id="po-vendor"
              className={INPUT}
              value={po.vendor_id}
              aria-invalid={Boolean(errorFor('vendor_id'))}
              onChange={(event) => change({ vendor_id: event.target.value })}
              onBlur={() => touch('vendor_id')}
            >
              <option value="">{vendors.loading ? 'Loading vendors…' : 'Choose a vendor'}</option>
              {(vendors.data ?? []).map((vendor) => (
                <option key={vendor.id} value={vendor.id}>
                  {vendor.name} ({vendor.id}){vendor.status === 'active' ? '' : `, ${vendor.status}`}
                </option>
              ))}
            </select>
            {vendors.error && <p className="mt-1 text-xs text-reject">The vendors could not be loaded: {vendors.error}</p>}
          </Field>
          <Field label="PO number" id="po-number" error={errorFor('po_number')}>
            <input
              id="po-number"
              className={cn(INPUT, 'num')}
              value={po.po_number}
              aria-invalid={Boolean(errorFor('po_number'))}
              onChange={(event) => {
                change({ po_number: event.target.value })
                touch('po_number')
              }}
            />
          </Field>
          <Field label="PO date" id="po-date" error={errorFor('po_date')}>
            <input
              id="po-date"
              type="date"
              max={today}
              className={cn(INPUT, 'num')}
              value={po.po_date}
              aria-invalid={Boolean(errorFor('po_date'))}
              onChange={(event) => {
                change({ po_date: event.target.value })
                touch('po_date')
              }}
            />
          </Field>
        </div>

        <div className="px-4 pt-4">
          <table className="w-full table-fixed text-left">
            <thead>
              <tr className="text-xs text-muted-foreground [&>th]:pb-1.5 [&>th]:font-medium">
                <th className="w-8">#</th>
                <th>Description</th>
                <th className="w-[120px] pl-3">Quantity</th>
                <th className="w-[150px] pl-3">Unit price (₹)</th>
                <th className="w-[140px] text-right">Amount</th>
                <th className="w-10"></th>
              </tr>
            </thead>
            <tbody>
              {po.lines.map((line, index) => {
                const amount = lineAmountPaise(line)
                const name = (field: string) => `lines.${index}.${field}`
                return (
                  <tr key={index} className="align-top [&>td]:pb-2">
                    <td className="num pt-1.5 text-muted-foreground">{index + 1}</td>
                    <td>
                      <input
                        aria-label={`Line ${index + 1} description`}
                        className={INPUT}
                        value={line.description}
                        aria-invalid={Boolean(errorFor(name('description')))}
                        onChange={(event) => changeLine(index, { description: event.target.value })}
                        onBlur={() => touch(name('description'))}
                      />
                      <Message text={errorFor(name('description'))} />
                    </td>
                    <td className="pl-3">
                      <input
                        aria-label={`Line ${index + 1} quantity`}
                        inputMode="decimal"
                        className={cn(INPUT, 'num text-right')}
                        value={line.quantity}
                        aria-invalid={Boolean(errorFor(name('quantity')))}
                        onChange={(event) => changeLine(index, { quantity: event.target.value })}
                        onBlur={() => touch(name('quantity'))}
                      />
                      <Message text={errorFor(name('quantity'))} />
                    </td>
                    <td className="pl-3">
                      <input
                        aria-label={`Line ${index + 1} unit price`}
                        inputMode="decimal"
                        className={cn(INPUT, 'num text-right')}
                        value={line.unit_price}
                        aria-invalid={Boolean(errorFor(name('unit_price')))}
                        onChange={(event) => changeLine(index, { unit_price: event.target.value })}
                        onBlur={() => touch(name('unit_price'))}
                      />
                      <Message text={errorFor(name('unit_price'))} />
                    </td>
                    <td className="num pt-1.5 text-right" data-testid={`line-amount-${index}`}>
                      {amount === null ? <span className="text-muted-foreground">—</span> : inr(fromPaise(amount))}
                    </td>
                    <td className="text-right">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={`Remove line ${index + 1}`}
                        disabled={po.lines.length === 1}
                        onClick={() => removeLine(index)}
                      >
                        <Trash2 />
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          <Message text={errorFor('lines')} />
          <Button type="button" variant="outline" size="sm" onClick={() => change({ lines: [...po.lines, { ...EMPTY_LINE }] })}>
            <Plus /> Add line
          </Button>
        </div>

        <div className="mt-4 flex items-center justify-between gap-6 border-t px-4 py-3">
          <div>
            <span className="text-xs text-muted-foreground">PO value, the sum of the lines (before tax)</span>
            <div className="num text-lg font-semibold" data-testid="po-value">
              {inr(fromPaise(valuePaise(po.lines)))}
            </div>
          </div>
          <div className="flex items-center gap-3">
            {failure && (
              <p className="text-sm text-reject" role="alert">
                {failure}
              </p>
            )}
            <Button type="button" variant="outline" onClick={onCancel}>
              Cancel
            </Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : 'Save purchase order'}
            </Button>
          </div>
        </div>
      </form>
    </Panel>
  )
}

function Field({ label, id, error, children }: { label: string; id: string; error?: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-muted-foreground">
        {label}
      </label>
      {children}
      <Message text={error} />
    </div>
  )
}

function Message({ text }: { text?: string }) {
  if (!text) return null
  return <p className="mt-1 text-xs text-reject">{text}</p>
}
