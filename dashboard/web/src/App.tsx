import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TopBar } from './components/TopBar';
import { LeftNav } from './components/LeftNav';
import { FleetView } from './views/FleetView';
import { AgentDetailView } from './views/AgentDetailView';
import { ApprovalsView } from './views/ApprovalsView';
import { IncidentsView } from './views/IncidentsView';
import { CostView } from './views/CostView';
import './styles/base.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 1000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const LayoutShell: React.FC = () => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', width: '100%' }}>
      <TopBar />
      <div style={{ display: 'flex', flex: 1, width: '100%' }}>
        <LeftNav />
        <main
          role="main"
          style={{
            flex: 1,
            padding: 'var(--space-6)',
            backgroundColor: 'var(--color-canvas)',
            maxWidth: '1680px',
            margin: '0 auto',
            width: '100%',
          }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<LayoutShell />}>
            <Route index element={<Navigate to="/fleet" replace />} />
            <Route path="fleet" element={<FleetView />} />
            <Route path="agents/:id" element={<AgentDetailView />} />
            <Route path="approvals" element={<ApprovalsView />} />
            <Route path="incidents" element={<IncidentsView />} />
            <Route path="cost" element={<CostView />} />
            <Route path="*" element={<Navigate to="/fleet" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
