// The reviewer's controls on a REVIEW run: a required comment, then approve or reject. When
// the purchase order was not confirmed by the process, the reviewer confirms or chooses it.

import { Check, X } from 'lucide-react'
import { useState } from 'react'

import { Eyebrow } from '@/components/common'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { type MatchResult, type PurchaseOrder, resolveRun, type RunDetail } from '@/lib/api'
import { inr } from '@/lib/format'
import { useApi } from '@/lib/useApi'

export function ReviewPanel({ run, onResolved }: { run: RunDetail; onResolved: (run: RunDetail) => void }) {
  const match = run.stages.find((stage) => stage.stage === 'match')?.result as MatchResult | null
  // The reviewer picks the PO whenever the process did not confirm one from the invoice.
  const mustChoosePO = match !== null && match.vendor_id !== null && match.po_match_type !== 'explicit_verified'
  const orders = useApi<PurchaseOrder[]>(mustChoosePO ? '/api/purchase-orders' : null)
  const vendorOrders = orders.data?.filter((po) => po.vendor_id === match?.vendor_id) ?? []

  const [poId, setPoId] = useState(run.po_id ?? '')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState<'approve' | 'reject' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const canApprove = run.pretax_amount !== null && (!mustChoosePO || poId !== '')
  const suggested = match?.po_match_type.startsWith('implied') ? match.po_id : null

  async function resolve(action: 'approve' | 'reject') {
    if (!comment.trim()) {
      setError('Write a comment first: it is kept with the decision.')
      return
    }
    setBusy(action)
    setError(null)
    try {
      onResolved(await resolveRun(run.id, action, comment, action === 'approve' && mustChoosePO ? poId : undefined))
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The decision could not be saved.')
      setBusy(null)
    }
  }

  return (
    <div className="mt-4 border-t pt-3.5">
      <Eyebrow>Reviewer's decision</Eyebrow>

      {mustChoosePO && (
        <label className="mt-2 block">
          <span className="text-[13px] text-foreground/80">Book against purchase order</span>
          <select
            value={poId}
            onChange={(event) => setPoId(event.target.value)}
            className="num mt-1 block h-8 w-full rounded-md border border-input bg-card px-2 text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
          >
            {poId === '' && <option value="">Choose a purchase order…</option>}
            {/* Until the list has loaded, the suggested PO is the only choice. */}
            {vendorOrders.length === 0 && poId !== '' && <option value={poId}>{poId}</option>}
            {vendorOrders.map((po) => (
              <option key={po.id} value={po.id}>
                {po.id} · {inr(po.remaining)} remaining{po.id === suggested ? ' · suggested' : ''}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="mt-2.5 block">
        <span className="text-[13px] text-foreground/80">Comment (required)</span>
        <Textarea
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          placeholder="Why are you approving or rejecting?"
          rows={2}
          maxLength={2000}
          className="mt-1 min-h-14 bg-card"
        />
      </label>

      {error && (
        <p className="mt-2 text-[13px] text-reject" role="alert">
          {error}
        </p>
      )}
      {run.pretax_amount === null && (
        <p className="mt-2 text-[13px] text-muted-foreground">
          The amount before tax is not known, so this invoice cannot be booked against a purchase order. It can only
          be rejected.
        </p>
      )}

      <div className="mt-3 flex gap-2">
        <Button
          disabled={busy !== null || !canApprove}
          onClick={() => resolve('approve')}
          className="flex-1 bg-approve text-white hover:bg-approve/90"
        >
          <Check /> {busy === 'approve' ? 'Saving…' : suggested && poId === suggested ? `Confirm ${poId} and approve` : 'Approve'}
        </Button>
        <Button
          variant="outline"
          disabled={busy !== null}
          onClick={() => resolve('reject')}
          className="border-reject-line bg-card text-reject hover:bg-reject-soft hover:text-reject"
        >
          <X /> {busy === 'reject' ? 'Saving…' : 'Reject'}
        </Button>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Approving adds {run.pretax_amount ? inr(run.pretax_amount) : 'the invoice'} before tax to the purchase order's
        billed amount.
      </p>
    </div>
  )
}
