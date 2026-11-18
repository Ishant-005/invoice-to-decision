// The frame around every screen: the header with navigation, "New run" and the reset button.

import { Plus, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { resetDemo } from '@/lib/api'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Dashboard' },
  { to: '/purchase-orders', label: 'Purchase orders' },
  { to: '/how-it-works', label: 'How it works' },
]

export function AppShell() {
  // Bumped after a reset: used as a `key`, it makes the current screen load its data afresh.
  const [resetCount, setResetCount] = useState(0)

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b bg-card">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-8 px-6">
          <Link to="/" className="flex items-center gap-2.5">
            <span className="flex size-7 items-center justify-center rounded-md bg-primary text-[13px] font-semibold text-primary-foreground">
              ₹
            </span>
            <span className="leading-tight">
              <span className="block font-semibold tracking-tight">Invoice-to-Decision</span>
              <span className="block text-[11px] text-muted-foreground">
                Meridian Home Retail · Accounts Payable
              </span>
            </span>
          </Link>

          <nav className="flex h-full items-stretch gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex items-center border-b-2 px-3 font-medium transition-colors',
                    isActive
                      ? 'border-primary text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground',
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2">
            <ResetButton onReset={() => setResetCount((count) => count + 1)} />
            <Button asChild>
              <Link to="/new">
                <Plus /> New run
              </Link>
            </Button>
          </div>
        </div>
      </header>

      <main key={resetCount} className="mx-auto max-w-[1400px] px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}

function ResetButton({ onReset }: { onReset: () => void }) {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function reset() {
    setBusy(true)
    setError(null)
    try {
      await resetDemo()
      setOpen(false)
      navigate('/')
      onReset()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The reset did not work.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      <AlertDialogTrigger asChild>
        <Button variant="ghost" className="text-muted-foreground">
          <RotateCcw /> Reset demo data
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Reset the demo data?</AlertDialogTitle>
          <AlertDialogDescription>
            Every run is deleted and the purchase order balances go back to their starting
            values, with the two seeded invoices as history. Saved AI readings are kept.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && <p className="text-reject">{error}</p>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={busy}
            onClick={(event) => {
              event.preventDefault() // keep the dialog open until the server has answered
              reset()
            }}
          >
            {busy ? 'Resetting…' : 'Reset demo data'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
