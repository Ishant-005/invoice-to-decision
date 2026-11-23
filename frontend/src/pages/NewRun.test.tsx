// The sample gallery shows a short scenario label on each card. The label is display only:
// starting a run sends the file name and nothing else.

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'

import { NewRun } from './NewRun'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const SAMPLES = [
  { case: 1, file: 'acme_2026-11-05.pdf', description: 'Acme Packaging: corrugated boxes', scanned: false, tag: 'Happy path' },
  { case: 5, file: 'zenith_2026-11-14.pdf', description: 'Zenith Facility Services: housekeeping', scanned: false, tag: 'Over PO value' },
]

test('each card shows its label, and a run is started with the file name only', async () => {
  const fetchMock = vi.fn(async (_url: string, options?: RequestInit) => {
    const body = options?.method === 'POST' ? { id: 'run-1' } : SAMPLES
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <MemoryRouter>
      <NewRun />
    </MemoryRouter>,
  )

  await waitFor(() => expect(screen.getAllByTestId('sample-tag')).toHaveLength(2))
  expect(screen.getAllByTestId('sample-tag').map((tag) => tag.textContent)).toEqual(['Happy path', 'Over PO value'])
  expect(screen.getByText('Labels describe what each sample tests. The process only receives the PDF.')).toBeTruthy()

  fireEvent.click(screen.getByText('Over PO value'))
  await waitFor(() => expect(fetchMock.mock.calls.some(([, options]) => options?.method === 'POST')).toBe(true))
  const sent = fetchMock.mock.calls.find(([, options]) => options?.method === 'POST')![1]!.body as FormData
  expect([...sent.entries()]).toEqual([['sample', 'zenith_2026-11-14.pdf']])
})
