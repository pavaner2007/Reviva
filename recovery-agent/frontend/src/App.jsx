import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Navigation from './components/Navigation';
import RecoveryQueue from './pages/RecoveryQueue';
import CaseDetail from './pages/CaseDetail';
import Dashboard from './pages/Dashboard';

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-slate-50">
        <Navigation />
        <main>
          <Routes>
            <Route path="/" element={<RecoveryQueue />} />
            <Route path="/case/:eventId" element={<CaseDetail />} />
            <Route path="/dashboard" element={<Dashboard />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
