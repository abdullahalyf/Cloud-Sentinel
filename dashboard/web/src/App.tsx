import { livePoll, startLiveStream } from './utils/live';
import React, { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TopBar } from './components/TopBar';
import { LeftNav } from './components/LeftNav';
import { ConnectionBanner } from './components/ConnectionBanner';
import { ToastProvider } from './components/Toast';
import { FleetView } from './views/FleetView';
import { AgentDetailView } from './views/AgentDetailView';
import { ApprovalsView } from './views/ApprovalsView';
import { IncidentsView } from './views/IncidentsView';
import { CostView } from './views/CostView';
import { GraphView } from './views/GraphView';
import './styles/base.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: livePoll,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const LayoutShell: React.FC = () => {
  const location = useLocation();
  return (
    <div className="shell">
      <LeftNav />
      <div className="content">
        <TopBar />
        <ConnectionBanner />
        <main role="main" className="main">
          <div key={location.pathname} className="page-enter">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  useEffect(() => startLiveStream(queryClient), []);
  useEffect(() => {
    // automated browsers (screenshots) get the finished frame, not mid-animation
    document.documentElement.dataset.static = navigator.webdriver === true ? 'true' : 'false';
  }, []);
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <Routes>
            <Route path="/" element={<LayoutShell />}>
              <Route index element={<Navigate to="/fleet" replace />} />
              <Route path="fleet" element={<FleetView />} />
              <Route path="agents/:id" element={<AgentDetailView />} />
              <Route path="approvals" element={<ApprovalsView />} />
              <Route path="incidents" element={<IncidentsView />} />
              <Route path="incidents/:incidentId" element={<IncidentsView />} />
              <Route path="cost" element={<CostView />} />
              <Route path="graph" element={<GraphView />} />
              <Route path="*" element={<Navigate to="/fleet" replace />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
};

export default App;
