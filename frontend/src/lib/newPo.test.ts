// The checks the "Add purchase order" form makes while the person types. The backend makes
// the same ones on save (backend/tests/integration/test_add_purchase_order.py).

import { expect, test } from 'vitest'

import type { PurchaseOrder } from './api'
import { checkNewPo, hundredths, lineAmountPaise, type NewPO, nextPoNumber, normalisePo, valuePaise } from './newPo'

const existing = [{ id: 'PO-2231' }, { id: 'PO-2301' }] as PurchaseOrder[]
const TODAY = '2026-11-18'
const good: NewPO = {
  vendor_id: 'V-001', po_number: 'PO-2310', po_date: '2026-11-10',
  lines: [{ description: 'Tape', quantity: '10', unit_price: '25.50' }],
}
const check = (changes: Partial<NewPO>) => checkNewPo({ ...good, ...changes }, existing, ['V-001', 'V-002'], TODAY)

test('a good purchase order has no errors', () => {
  expect(check({})).toEqual({})
  expect(check({ po_date: TODAY })).toEqual({})
})

test('PO numbers collide after normalisation', () => {
  for (const text of ['PO-2231', '2231', 'po 2231', 'P.O. #2231']) expect(normalisePo(text)).toBe('2231')
  expect(check({ po_number: '2231' })).toEqual({ po_number: 'PO-2231 already exists. Choose a different number.' })
  expect(check({ po_number: 'PO-' }).po_number).toContain('Enter a PO number')
})

test('the suggested number is one more than the highest', () => {
  expect(nextPoNumber(existing)).toBe('PO-2302')
  expect(nextPoNumber([])).toBe('PO-1')
})

test('the vendor must be in the list and the date not in the future', () => {
  expect(check({ vendor_id: '' })).toEqual({ vendor_id: 'Choose a vendor from the list.' })
  expect(check({ po_date: '2026-11-19' })).toEqual({ po_date: 'The PO date cannot be in the future.' })
  expect(check({ po_date: '' })).toEqual({ po_date: 'Enter the PO date.' })
})

test('quantities and prices must be plain numbers above zero', () => {
  for (const bad of ['0', '0.00', '-5', '', 'abc', '1e3', 'NaN', '1.234', '1,000']) {
    expect(hundredths(bad), bad).toBeNull()
    expect(Object.keys(check({ lines: [{ description: 'Tape', quantity: bad, unit_price: '1' }] }))).toEqual(['lines.0.quantity'])
    expect(Object.keys(check({ lines: [{ description: 'Tape', quantity: '1', unit_price: bad }] }))).toEqual(['lines.0.unit_price'])
  }
  expect(check({ lines: [] })).toEqual({ lines: 'Add at least one line.' })
  expect(check({ lines: [{ description: ' ', quantity: '1', unit_price: '1' }] })).toEqual({
    'lines.0.description': 'Describe what is being ordered.',
  })
})

test('line amounts and the value are exact, rounded to whole paise', () => {
  expect(lineAmountPaise({ description: '', quantity: '10', unit_price: '25.50' })).toBe(25500n)
  expect(lineAmountPaise({ description: '', quantity: '2.5', unit_price: '99.99' })).toBe(24998n) // 249.975
  expect(lineAmountPaise({ description: '', quantity: '', unit_price: '5' })).toBeNull()
  expect(
    valuePaise([
      { description: '', quantity: '10', unit_price: '25.50' },
      { description: '', quantity: '2.5', unit_price: '99.99' },
      { description: '', quantity: 'x', unit_price: '1' },
    ]),
  ).toBe(50498n)
})
