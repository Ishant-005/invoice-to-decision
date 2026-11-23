// The "Add vendor" form. Plain code, no AI. Every check is made by the backend
// (backend/app/api/vendors.py): the form asks for them while the person types and shows the
// answer, so the rules exist in one place only.

import { TriangleAlert } from 'lucide-react'
import { type FormEvent, useRef, useState } from 'react'

import { Panel } from '@/components/common'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export interface Vendor {
  id: string
  name: string
  tax_id: string
  status: string
}

interface VendorCheck {
  vendor_id: string // the ID the new vendor would get
  errors: Record<string, string> // {field: plain message}
  similar: { id: string; name: string; score: number } | null // a look-alike existing vendor
}

const INPUT =
  'h-8 w-full rounded-md border border-input bg-background px-2.5 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50 aria-invalid:border-reject'

async function post(path: string, body: unknown): Promise<{ status: number; body: unknown }> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return { status: response.status, body: await response.json().catch(() => null) }
}

export function AddVendor({ onAdded, onCancel }: { onAdded: (vendor: Vendor) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [gstin, setGstin] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [check, setCheck] = useState<VendorCheck | null>(null)
  const [triedToSave, setTriedToSave] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  // Checks are asked for a moment after the last keystroke; only the latest answer is kept.
  const timer = useRef<number | undefined>(undefined)
  const latest = useRef(0)

  function askForCheck(nextName: string, nextGstin: string) {
    window.clearTimeout(timer.current)
    const mine = ++latest.current
    timer.current = window.setTimeout(async () => {
      try {
        const answer = await post('/api/vendors/check', { name: nextName, gstin: nextGstin })
        if (mine === latest.current && answer.status === 200) setCheck(answer.body as VendorCheck)
      } catch {
        // Not reachable right now: the checks are made again when the form is saved.
      }
    }, 250)
  }

  function change(nextName: string, nextGstin: string) {
    setName(nextName)
    setGstin(nextGstin)
    setFailure(null)
    // A different name is a different question, so the tick does not carry over.
    if (nextName !== name) setConfirmed(false)
    askForCheck(nextName, nextGstin)
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    event.stopPropagation()
    setTriedToSave(true)
    window.clearTimeout(timer.current)
    latest.current++
    setSaving(true)
    try {
      const answer = await post('/api/vendors', { name, gstin, confirm_similar: confirmed })
      if (answer.status === 201) return onAdded(answer.body as Vendor)
      // 422: a field is wrong. 409: the name is a look-alike and the box is not ticked.
      if (answer.status === 422 || answer.status === 409) setCheck(answer.body as VendorCheck)
      else setFailure(`The vendor could not be saved (${answer.status}).`)
    } catch {
      setFailure('The server could not be reached. Check that it is running.')
    } finally {
      setSaving(false)
    }
  }

  const errors = check?.errors ?? {}
  // A message about an empty name waits until Save is pressed; other messages show at once.
  const nameError = name.trim() || triedToSave ? errors.name : undefined
  const similar = !errors.name ? (check?.similar ?? null) : null

  return (
    <Panel className="mb-4">
      <form onSubmit={save} noValidate data-testid="add-vendor-form">
        <div className="border-b px-4 py-2.5">
          <h2 className="font-semibold">Add vendor</h2>
          <p className="text-xs text-muted-foreground">
            This form stands in for the company's vendor onboarding process. The vendor is active at once and gets the
            next free vendor ID{check ? ` (${check.vendor_id})` : ''}. Reset demo data removes it again.
          </p>
        </div>

        <div className="grid grid-cols-[2fr_1fr] gap-4 px-4 pt-4">
          <div>
            <label htmlFor="vendor-name" className="mb-1 block text-xs font-medium text-muted-foreground">
              Vendor name
            </label>
            <input
              id="vendor-name"
              className={INPUT}
              value={name}
              autoFocus
              aria-invalid={Boolean(nameError)}
              onChange={(event) => change(event.target.value, gstin)}
            />
            {nameError && <p className="mt-1 text-xs text-reject">{nameError}</p>}
          </div>
          <div>
            <label htmlFor="vendor-gstin" className="mb-1 block text-xs font-medium text-muted-foreground">
              GSTIN <span className="font-normal">(optional)</span>
            </label>
            <input
              id="vendor-gstin"
              className={cn(INPUT, 'code uppercase')}
              value={gstin}
              maxLength={20}
              aria-invalid={Boolean(errors.gstin)}
              onChange={(event) => change(name, event.target.value)}
            />
            {errors.gstin && <p className="mt-1 text-xs text-reject">{errors.gstin}</p>}
          </div>
        </div>

        {similar && (
          <div className="mx-4 mt-4 rounded-md border border-review-line bg-review-soft p-3" role="alert" data-testid="similar-warning">
            <p className="flex items-start gap-2 font-medium text-review">
              <TriangleAlert className="mt-0.5 size-4 shrink-0" />
              <span>
                This name looks like an existing vendor: {similar.name} ({similar.id}), {similar.score}% alike.
              </span>
            </p>
            <p className="mt-1 pl-6 text-[13px] text-foreground/80">
              Look-alike vendor names are a known fraud pattern, which the invoice checks also guard against. Add it only
              if you are sure it is a different company.
            </p>
            <label className="mt-2 flex items-center gap-2 pl-6 text-[13px] font-medium">
              <input
                type="checkbox"
                className="size-4 accent-primary"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              This is a different vendor from {similar.name}
            </label>
          </div>
        )}

        <div className="mt-4 flex items-center justify-end gap-3 border-t px-4 py-3">
          {failure && (
            <p className="text-sm text-reject" role="alert">
              {failure}
            </p>
          )}
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={saving || (similar !== null && !confirmed)}>
            {saving ? 'Saving…' : 'Save vendor'}
          </Button>
        </div>
      </form>
    </Panel>
  )
}
