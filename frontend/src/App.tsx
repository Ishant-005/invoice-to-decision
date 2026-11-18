import { BrowserRouter, Route, Routes } from 'react-router'

import { AppShell } from '@/components/AppShell'
import { EmptyState } from '@/components/common'
import { Dashboard } from '@/pages/Dashboard'
import { HowItWorks } from '@/pages/HowItWorks'
import { NewRun } from '@/pages/NewRun'
import { PurchaseOrders } from '@/pages/PurchaseOrders'
import { RunView } from '@/pages/RunView'

// The five screens. Every one of them reads its data from the backend API.
function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Dashboard />} />
          <Route path="new" element={<NewRun />} />
          <Route path="runs/:runId" element={<RunView />} />
          <Route path="purchase-orders" element={<PurchaseOrders />} />
          <Route path="how-it-works" element={<HowItWorks />} />
          <Route
            path="*"
            element={<EmptyState title="There is no page at this address">Use the menu above.</EmptyState>}
          />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App
