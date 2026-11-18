import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

type BackendStatus = 'checking' | 'ok' | 'unreachable'

const STAGES = ['Receive', 'Extract', 'Validate', 'Match', 'Rules', 'Decide']

// Placeholder home page for Milestone 0. It makes one real call to the backend
// health endpoint so we can see the two halves of the app talking to each other.
function App() {
  const [backend, setBackend] = useState<BackendStatus>('checking')

  useEffect(() => {
    fetch('/api/health')
      .then((response) => setBackend(response.ok ? 'ok' : 'unreachable'))
      .catch(() => setBackend('unreachable'))
  }, [])

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 p-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Invoice-to-Decision</h1>
        <p className="mt-2 text-muted-foreground">
          Reads a vendor invoice, checks it against purchase orders and company rules, and
          explains whether to approve it, send it to a person, or reject it.
        </p>
      </header>

      <Card>
        <CardHeader>
          <CardTitle>Project scaffold</CardTitle>
          <CardDescription>
            This is a placeholder page. The dashboard and run view arrive in later milestones.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex items-center gap-2 text-sm">
            <span>Backend:</span>
            {backend === 'checking' && <Badge variant="secondary">Checking…</Badge>}
            {backend === 'ok' && <Badge>Connected</Badge>}
            {backend === 'unreachable' && <Badge variant="destructive">Not reachable</Badge>}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>Pipeline:</span>
            {STAGES.map((stage, index) => (
              <Badge key={stage} variant="outline">
                {index + 1}. {stage}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>
    </main>
  )
}

export default App
