// The "Add vendor" form shows what the backend's checks say. These tests answer the two API
// calls from the data below and check the form's side: messages are shown, and a look-alike
// name cannot be saved until the box is ticked. (The rules themselves are tested in the
// backend: tests/integration/test_add_vendor.py.)

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { AddVendor } from './AddVendor'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const SIMILAR = { id: 'V-001', name: 'Acme Packaging Pvt Ltd', score: 96 }

/** Stand in for the backend: `check` is what it says about whatever is typed. */
function backend(check: { errors: Record<string, string>; similar: typeof SIMILAR | null }) {
  const saved: { name: string; gstin: string; confirm_similar: boolean }[] = []
  vi.stubGlobal('fetch', async (path: string, init: RequestInit) => {
    const sent = JSON.parse(init.body as string)
    const answer = { vendor_id: 'V-006', ...check }
    if (path === '/api/vendors/check') return new Response(JSON.stringify(answer))
    if (Object.keys(check.errors).length) return new Response(JSON.stringify(answer), { status: 422 })
    if (check.similar && !sent.confirm_similar) return new Response(JSON.stringify(answer), { status: 409 })
    saved.push(sent)
    return new Response(JSON.stringify({ id: 'V-006', name: sent.name, tax_id: sent.gstin, status: 'active' }), { status: 201 })
  })
  return saved
}

const type = (label: string | RegExp, text: string) => fireEvent.change(screen.getByLabelText(label), { target: { value: text } })
const saveButton = () => screen.getByRole('button', { name: 'Save vendor' }) as HTMLButtonElement

test('a look-alike name shows a warning naming the vendor and needs a tick before saving', async () => {
  const saved = backend({ errors: {}, similar: SIMILAR })
  const onAdded = vi.fn()
  render(<AddVendor onAdded={onAdded} onCancel={() => {}} />)

  type('Vendor name', 'Acme Packagng Pvt Ltd')
  const warning = await screen.findByTestId('similar-warning')
  expect(warning.textContent).toContain('Acme Packaging Pvt Ltd (V-001), 96% alike')
  expect(saveButton().disabled).toBe(true)

  fireEvent.click(screen.getByRole('checkbox'))
  expect(saveButton().disabled).toBe(false)
  fireEvent.click(saveButton())

  await waitFor(() => expect(onAdded).toHaveBeenCalled())
  expect(saved).toEqual([{ name: 'Acme Packagng Pvt Ltd', gstin: '', confirm_similar: true }])
})

test('changing the name clears the tick', async () => {
  backend({ errors: {}, similar: SIMILAR })
  render(<AddVendor onAdded={() => {}} onCancel={() => {}} />)
  type('Vendor name', 'Acme Packagng')
  await screen.findByTestId('similar-warning')
  fireEvent.click(screen.getByRole('checkbox'))
  type('Vendor name', 'Acme Packagin')
  expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false)
  expect(saveButton().disabled).toBe(true)
})

test('messages from the checks are shown under their fields and nothing is saved', async () => {
  const saved = backend({
    errors: { name: 'Acme Packaging Pvt Ltd (V-001) already has this name.', gstin: 'This GSTIN is already used by Acme Packaging Pvt Ltd (V-001).' },
    similar: null,
  })
  const onAdded = vi.fn()
  render(<AddVendor onAdded={onAdded} onCancel={() => {}} />)
  type('Vendor name', 'Acme Packaging')
  type(/GSTIN/, '06AAACA0001A1Z1')
  await screen.findByText('Acme Packaging Pvt Ltd (V-001) already has this name.')
  await screen.findByText('This GSTIN is already used by Acme Packaging Pvt Ltd (V-001).')
  fireEvent.click(saveButton())
  await waitFor(() => expect(saveButton().textContent).toBe('Save vendor'))
  expect(onAdded).not.toHaveBeenCalled()
  expect(saved).toEqual([])
})

test('a clean name saves without any tick, and the note about onboarding is shown', async () => {
  const saved = backend({ errors: {}, similar: null })
  const onAdded = vi.fn()
  render(<AddVendor onAdded={onAdded} onCancel={() => {}} />)
  expect(screen.getByText(/stands in for the company's vendor onboarding process/)).toBeTruthy()
  type('Vendor name', 'Northwind Traders')
  fireEvent.click(saveButton())
  await waitFor(() => expect(onAdded).toHaveBeenCalledWith(expect.objectContaining({ id: 'V-006' })))
  expect(saved[0].confirm_similar).toBe(false)
  expect(screen.queryByTestId('similar-warning')).toBeNull()
})
