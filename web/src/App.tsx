import { useEffect, useMemo, useState } from 'react';
import { TopBar } from '@/components/layout/TopBar';
import { Sidebar, type NavKey } from '@/components/layout/Sidebar';
import { Footer } from '@/components/layout/Footer';
import { LoadingState } from '@/components/ui/LoadingState';
import { createSource, type SourceMode } from '@/data/createSource';
import { RemoteNodeSource } from '@/data/remoteNodeSource';
import type { DataSource, SourceStatus } from '@/data/source';
import type { Snapshot, TrendPoint } from '@/data/types';
import type { Range } from '@/components/charts/DeformationTrend';
import {
  AlertsView,
  AnalyticsView,
  DashboardView,
  HealthView,
  HistoricalView,
  LiveMapView,
  NodesView,
  PredictionView,
  ReportsView,
  SettingsView,
} from '@/views';
import { AuthProvider, useAuth } from '@/auth/AuthContext';
import {
  LoginView,
  RegisterView,
  ForgotPasswordView,
  ResetPasswordView,
} from '@/views/auth';

type AuthViewMode = 'none' | 'login' | 'register' | 'forgot-password' | 'reset-password';

function MainApp() {
  const { user, logout, handleGoogleCallback } = useAuth();
  const [authView, setAuthView] = useState<AuthViewMode>('none');
  const [resetToken, setResetToken] = useState<string>('');

  const [sourceMode, setSourceMode] = useState<SourceMode>(() => {
    return (localStorage.getItem('mineguard_source_mode') as SourceMode) || 'remote';
  });
  const [source, setSource] = useState<DataSource | null>(null);
  const [status, setStatus] = useState<SourceStatus>({ kind: 'simulated', connected: false });
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [history, setHistory] = useState<TrendPoint[]>([]);
  const [nav, setNav] = useState<NavKey>('dashboard');
  const [range, setRange] = useState<Range>('24H');
  const [selected, setSelected] = useState<number | null>(null);
  const [clock, setClock] = useState(new Date());

  // Listen for OAuth callbacks or password reset tokens in URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const token = params.get('token') || params.get('reset_token');

    if (code) {
      const redirectUri = window.location.origin + window.location.pathname;
      handleGoogleCallback(code, redirectUri)
        .then(() => {
          setAuthView('none');
        })
        .catch((err) => {
          console.error('Google OAuth callback error:', err);
          setAuthView('login');
        })
        .finally(() => {
          window.history.replaceState({}, document.title, window.location.pathname);
        });
    } else if (token) {
      setResetToken(token);
      setAuthView('reset-password');
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  }, [handleGoogleCallback]);

  const handleModeChange = (newMode: SourceMode) => {
    localStorage.setItem('mineguard_source_mode', newMode);
    setSourceMode(newMode);
    setSnap(null);
  };

  useEffect(() => {
    let disposed = false;
    let created: DataSource | null = null;
    void createSource(sourceMode).then((s) => {
      if (disposed) {
        s.stop();
        return;
      }
      created = s;
      setSource(s);
    });
    return () => {
      disposed = true;
      created?.stop();
    };
  }, [sourceMode]);

  useEffect(() => {
    if (!source) return;
    const unsubSnap = source.subscribe(setSnap);
    const unsubStatus = source.onStatus(setStatus);
    source.start();
    return () => {
      unsubSnap();
      unsubStatus();
      source.stop();
    };
  }, [source]);

  useEffect(() => {
    const id = window.setInterval(() => setClock(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  // Default detail panels to Node 01 (NODE-001) in remote API mode,
  // or to the riskiest node in simulation mode.
  const riskiest = useMemo(() => {
    if (!snap) return null;
    const live = snap.nodes.filter((n) => n.online);
    return live.reduce<null | typeof live[number]>(
      (best, n) => (best === null || n.riskScore > best.riskScore ? n : best),
      null,
    );
  }, [snap]);

  const defaultAddr = sourceMode === 'remote' ? 16 : (riskiest?.addr ?? snap?.nodes[0]?.addr ?? 0);
  const selectedAddr = selected ?? defaultAddr;
  const selectedNode = snap?.nodes.find((n) => n.addr === selectedAddr);

  useEffect(() => {
    if (snap && source) setHistory([...source.history(selectedAddr)]);
  }, [snap, selectedAddr, source]);

  // Handle alert acknowledgment in real-time
  const handleAckAlert = (alertId: string) => {
    if (source instanceof RemoteNodeSource) {
      source.ackAlert(alertId);
    }
  };

  // If an authentication view is opened, render it with smooth two-way links
  if (authView === 'login') {
    return (
      <LoginView
        onNavigateDashboard={() => setAuthView('none')}
        onSuccess={() => setAuthView('none')}
        onNavigateRegister={() => setAuthView('register')}
        onNavigateForgotPassword={() => setAuthView('forgot-password')}
      />
    );
  }

  if (authView === 'register') {
    return (
      <RegisterView
        onNavigateDashboard={() => setAuthView('none')}
        onSuccess={() => setAuthView('none')}
        onNavigateLogin={() => setAuthView('login')}
      />
    );
  }

  if (authView === 'forgot-password') {
    return (
      <ForgotPasswordView
        onNavigateDashboard={() => setAuthView('none')}
        onNavigateLogin={() => setAuthView('login')}
        onNavigateResetPassword={(tok) => {
          if (tok) setResetToken(tok);
          setAuthView('reset-password');
        }}
      />
    );
  }

  if (authView === 'reset-password') {
    return (
      <ResetPasswordView
        initialToken={resetToken}
        onNavigateDashboard={() => setAuthView('none')}
        onNavigateLogin={() => setAuthView('login')}
      />
    );
  }

  if (!snap) {
    return (
      <div className="grid h-full place-items-center bg-plane text-sm text-ink-3">
        <LoadingState
          message="Connecting to Node 1 Live Telemetry Stream..."
          subMessage={
            sourceMode === 'remote'
              ? 'Streaming from mineguard-api.tenant.eu.org'
              : 'Connecting to local backend service on port 8000'
          }
        />
        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={() => handleModeChange('simulated')}
            className="rounded-lg bg-surface-2 px-3 py-1.5 text-xs font-semibold text-ink-2 hover:bg-surface-3 hover:text-brand transition-colors"
          >
            Switch to Simulator
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-lg bg-brand px-3 py-1.5 text-xs font-bold text-white shadow-glow transition-colors"
          >
            Retry Connection
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-plane">
      <TopBar
        alertCount={snap.alerts.length}
        status={status}
        mode={sourceMode}
        onModeChange={handleModeChange}
        onNavigateAlerts={() => setNav('alerts')}
        user={user}
        onLogout={logout}
        onOpenLogin={() => setAuthView('login')}
      />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        <Sidebar
          active={nav}
          onSelect={setNav}
          alertCount={snap.alerts.length}
          clock={clock}
          gatewayVolts={snap.gatewayVolts}
          gatewayBatteryPct={snap.gatewayBatteryPct}
        />

        <main className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
          {nav === 'dashboard' && (
            <DashboardView
              snap={snap}
              history={history}
              range={range}
              onRange={setRange}
              selectedAddr={selectedAddr}
              onSelect={setSelected}
              onToggleNode={source?.toggleNode ? (addr) => source.toggleNode!(addr) : undefined}
              sourceMode={sourceMode}
              onNavigateAlerts={() => setNav('alerts')}
            />
          )}

          {nav === 'live-map' && (
            <LiveMapView
              nodes={snap.nodes}
              links={snap.links}
              day={snap.day}
              faceX={snap.faceX}
              selectedAddr={selectedAddr}
              onSelect={setSelected}
              onToggleNode={source?.toggleNode ? (addr) => source.toggleNode!(addr) : undefined}
            />
          )}

          {nav === 'nodes' && (
            <NodesView
              nodes={snap.nodes}
              selectedAddr={selectedAddr}
              onSelect={setSelected}
            />
          )}

          {nav === 'alerts' && (
            <AlertsView
              alerts={snap.alerts}
              onAckAlert={handleAckAlert}
            />
          )}

          {nav === 'analytics' && (
            <AnalyticsView
              history={history}
              range={range}
              onRange={setRange}
              nodeLabel={selectedNode?.label}
            />
          )}

          {nav === 'historical' && (
            <HistoricalView
              history={history}
              nodeLabel={selectedNode?.label}
              onRefresh={() => {
                if (source) setHistory([...source.history(selectedAddr)]);
              }}
            />
          )}

          {nav === 'prediction' && (
            <PredictionView
              snap={snap}
              selectedAddr={selectedAddr}
              onSelect={setSelected}
            />
          )}

          {nav === 'reports' && (
            <ReportsView snap={snap} />
          )}

          {nav === 'settings' && (
            <SettingsView nodeId={selectedNode?.label ? selectedNode.label.split(' ')[0] : 'NODE-001'} />
          )}

          {nav === 'health' && (
            <HealthView snap={snap} />
          )}
        </main>
      </div>

      <Footer />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <MainApp />
    </AuthProvider>
  );
}
