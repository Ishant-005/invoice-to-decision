// Adding a purchase order: the checks and the sums the form shows while the person types.
// Plain code, no AI. The backend makes the same checks again when the form is saved
// (backend/app/api/purchase_orders.py); its answer is the one that counts.

import type { PurchaseOrder } from './api'

export interface NewLine {
  description: string
  quantity: string
  unit_price: string
}

export interface NewPO {
  vendor_id: string
  po_number: string
  po_date: string // YYYY-MM-DD
  lines: NewLine[]
}

/** {field: plain message}. Line fields are named like "lines.0.quantity". */
export type Errors = Record<string, string>

export const EMPTY_LINE: NewLine = { description: '', quantity: '', unit_price: '' }

/** "PO-2231", "P.O. #2231", "po 2231" and "2231" all become "2231": the same rule the
 *  Match stage uses to read a PO number off an invoice. */
export function normalisePo(reference: string): string {
  let text = reference.toUpperCase().replace(/[^A-Z0-9]/g, '')
  for (const prefix of ['PURCHASEORDER', 'PO', 'NO']) if (text.startsWith(prefix)) text = text.slice(prefix.length)
  return text
}

/** The next free number: one more than the highest numbered PO. */
export function nextPoNumber(orders: PurchaseOrder[]): string {
  const numbers = orders.map((po) => normalisePo(po.id)).filter((key) => /^\d{1,12}$/.test(key)).map(Number)
  return `PO-${numbers.length ? Math.max(...numbers) + 1 : 1}`
}

/** Today's date in India (UTC+5:30), where the buyer is; the backend uses the same date. */
export function todayInIndia(): string {
  return new Date(Date.now() + 5.5 * 60 * 60 * 1000).toISOString().slice(0, 10)
}

/** A quantity or price as whole hundredths ("2.5" -> 250n), or null if it is not a plain
 *  number above zero with at most 2 decimal places. Whole numbers only, never a float. */
export function hundredths(text: string): bigint | null {
  const match = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(text.trim())
  if (!match) return null
  const value = BigInt(match[1]) * 100n + BigInt((match[2] ?? '').padEnd(2, '0'))
  return value > 0n ? value : null
}

/** Quantity times unit price in whole paise, rounded half up; null until both are valid. */
export function lineAmountPaise(line: NewLine): bigint | null {
  const quantity = hundredths(line.quantity)
  const price = hundredths(line.unit_price)
  if (quantity === null || price === null) return null
  return (quantity * price + 50n) / 100n
}

/** The PO value: the sum of the lines that can be worked out so far. */
export function valuePaise(lines: NewLine[]): bigint {
  return lines.reduce((sum, line) => sum + (lineAmountPaise(line) ?? 0n), 0n)
}

export function checkNewPo(po: NewPO, orders: PurchaseOrder[], vendorIds: string[], today: string): Errors {
  const errors: Errors = {}

  if (!vendorIds.includes(po.vendor_id)) errors.vendor_id = 'Choose a vendor from the list.'

  const key = normalisePo(po.po_number)
  const taken = orders.find((other) => normalisePo(other.id) === key)
  if (key.length < 1 || key.length > 12) errors.po_number = 'Enter a PO number of 1 to 12 letters or digits, such as PO-2310.'
  else if (taken) errors.po_number = `${taken.id} already exists. Choose a different number.`

  if (!/^\d{4}-\d{2}-\d{2}$/.test(po.po_date)) errors.po_date = 'Enter the PO date.'
  else if (po.po_date > today) errors.po_date = 'The PO date cannot be in the future.'

  if (po.lines.length === 0) errors.lines = 'Add at least one line.'
  po.lines.forEach((line, index) => {
    const description = line.description.trim()
    if (!description) errors[`lines.${index}.description`] = 'Describe what is being ordered.'
    else if (description.length > 200) errors[`lines.${index}.description`] = 'Keep the description under 200 characters.'
    if (hundredths(line.quantity) === null)
      errors[`lines.${index}.quantity`] = 'Enter a quantity above zero, with at most 2 decimal places.'
    if (hundredths(line.unit_price) === null)
      errors[`lines.${index}.unit_price`] = 'Enter a price above zero, with at most 2 decimal places.'
  })
  return errors
}

/** Save the purchase order. Answers with the new PO, or with the backend's messages. */
export async function addPurchaseOrder(po: NewPO): Promise<{ po: PurchaseOrder } | { errors: Errors; message: string }> {
  let response: Response
  try {
    response = await fetch('/api/purchase-orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(po),
    })
  } catch {
    return { errors: {}, message: 'The server could not be reached. Check that it is running.' }
  }
  const body = await response.json().catch(() => null)
  if (response.ok && body) return { po: body as PurchaseOrder }
  const errors: Errors = body?.errors ?? {}
  const message = Object.keys(errors).length
    ? 'Some fields need attention.'
    : `The purchase order could not be saved (${response.status}).`
  return { errors, message }
}
