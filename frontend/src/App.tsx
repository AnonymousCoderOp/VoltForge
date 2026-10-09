import { useCallback, useEffect, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BatteryCharging,
  Bell,
  CalendarDays,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  CloudSun,
  Cpu,
  Gauge,
  Grid2X2,
  Leaf,
  LayoutDashboard,
  Menu,
  Moon,
  Power,
  RefreshCw,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Thermometer,
  TrendingUp,
  Wifi,
  WifiOff,
  Wind,
  X,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiGet, apiPost, getWebSocketUrl } from "./lib/api";

type Theme = "light" | "dark";
type NavItem = { id: string; label: string; icon: typeof LayoutDashboard };

const navItems: NavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "dispatch", label: "Energy dispatch", icon: Activity },
  { id: "resilience", label: "Resilience lab", icon: ShieldCheck },
  { id: "insights", label: "Insights & impact", icon: TrendingUp },
];

const number = (value: unknown, digits = 0): string => {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString("en-IN", { maximumFractionDigits: digits, minimumFractionDigits: digits })
    : "—";
};

const money = (value: unknown): string => {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })
    : "—";
};

const timeLabel = (row: Record<string, any>, index: number): string => {
  if (row.hour !== undefined && row.hour !== null) {
    return `${String(row.hour).padStart(2, "0")}:00`;
  }
  if (row.timestamp) {
    const date = new Date(row.timestamp);
    if (!Number.isNaN(date.getTime())) {
      return date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
  }
  return String(index + 1);
};

function MiniLine({ values = [28, 42, 34, 58, 49, 72, 63], positive = true }: { values?: number[]; positive?: boolean }) {
  const width = 92;
  const height = 32;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const points = values.map((v, i) => {
    const x = (i / Math.max(values.length - 1, 1)) * width;
    const y = height - 4 - ((v - min) / Math.max(max - min, 1)) * (height - 8);
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg className={positive ? "mini-line is-positive" : "mini-line"} viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MetricCard({
  label,
  value,
  unit,
  icon: Icon,
  tone,
  foot,
  trend,
  delay = 0,
  line,
}: {
  label: string;
  value: string;
  unit?: string;
  icon: typeof Zap;
  tone: string;
  foot: string;
  trend?: string;
  delay?: number;
  line?: number[];
}) {
  return (
    <motion.article
      className="metric-card panel"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.42, delay, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -3, transition: { duration: 0.18 } }}
    >
      <div className="metric-top">
        <span className={`metric-icon ${tone}`}><Icon size={19} strokeWidth={2} /></span>
        <span className="metric-label">{label}</span>
        {trend && <span className="metric-trend"><ArrowDownRight size={13} />{trend}</span>}
      </div>
      <div className="metric-value-row">
        <strong className="metric-value">{value}</strong>
        {unit && <span className="metric-unit">{unit}</span>}
      </div>
      <div className="metric-bottom">
        <span className="metric-foot">{foot}</span>
        <MiniLine values={line} />
      </div>
    </motion.article>
  );
}

function SectionHeading({ eyebrow, title, detail, right }: { eyebrow?: string; title: string; detail?: string; right?: ReactNode }) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2>{title}</h2>
        {detail && <p className="section-detail">{detail}</p>}
      </div>
      {right && <div className="section-heading-right">{right}</div>}
    </div>
  );
}

function EmptyChart({ message }: { message: string }) {
  return <div className="empty-chart"><Activity size={21} /><span>{message}</span></div>;
}

function App() {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const saved = localStorage.getItem("voltforge-theme");
      return saved === "light" ? "light" : "dark";
    } catch {
      return "dark";
    }
  });
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [activeNav, setActiveNav] = useState("overview");
  const [refreshing, setRefreshing] = useState(false);
  const [apiConnected, setApiConnected] = useState(false);
  const [wsStatus, setWsStatus] = useState<"connecting" | "connected" | "reconnecting">("connecting");
  const [lastPulse, setLastPulse] = useState<number | null>(null);
  const [liveSnapshot, setLiveSnapshot] = useState<Record<string, any> | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [toast, setToast] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);

  const [health, setHealth] = useState<Record<string, any> | null>(null);
  const [state, setState] = useState<Record<string, any> | null>(null);
  const [forecastResponse, setForecastResponse] = useState<Record<string, any> | null>(null);
  const [dispatchResponse, setDispatchResponse] = useState<Record<string, any> | null>(null);
  const [metrics, setMetrics] = useState<Record<string, any> | null>(null);
  const [resilience, setResilience] = useState<Record<string, any> | null>(null);
  const [sustainability, setSustainability] = useState<Record<string, any> | null>(null);
  const [financialHistory, setFinancialHistory] = useState<Record<string, any> | null>(null);
  const [telemetry, setTelemetry] = useState<Record<string, any> | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("voltforge-theme", theme);
    } catch {
      // The theme still works if browser storage is disabled.
    }
  }, [theme]);

  const refreshData = useCallback(async () => {
    setRefreshing(true);
    const endpoints = [
      ["/health", setHealth],
      ["/state", setState],
      ["/forecast", setForecastResponse],
      ["/dispatch", setDispatchResponse],
      ["/metrics", setMetrics],
      ["/resilience", setResilience],
      ["/sustainability", setSustainability],
      ["/analytics/financial-history", setFinancialHistory],
      ["/battery/telemetry", setTelemetry],
    ] as const;

    const results = await Promise.allSettled(
      endpoints.map(async ([path, setter]) => {
        const result = await apiGet<Record<string, any>>(path);
        setter(result);
        return path;
      }),
    );
    const failed = results
      .map((result, index) => result.status === "rejected" ? endpoints[index][0] : null)
      .filter((path): path is string => Boolean(path));

    setApiConnected(failed.length < endpoints.length);
    if (failed.length === endpoints.length) {
      setApiError("VoltForge API is unreachable. Start the FastAPI backend on port 8000.");
    } else if (failed.length > 0) {
      setApiError(`Some data could not refresh: ${failed.join(", ")}`);
    } else {
      setApiError(null);
    }
    setRefreshing(false);
  }, []);

  useEffect(() => {
    void refreshData();
    const interval = window.setInterval(() => void refreshData(), 20000);
    return () => window.clearInterval(interval);
  }, [refreshData]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: number | undefined;
    let closedByApp = false;

    const connect = () => {
      if (closedByApp) return;
      setWsStatus("connecting");
      try {
        socket = new WebSocket(getWebSocketUrl());
        socket.onopen = () => setWsStatus("connected");
        socket.onmessage = (event) => {
          try {
            const parsed = JSON.parse(event.data) as Record<string, any>;
            setLiveSnapshot(parsed);
            setLastPulse(Date.now());
          } catch {
            // Ignore malformed messages without dropping the connection.
          }
        };
        socket.onerror = () => socket?.close();
        socket.onclose = () => {
          if (!closedByApp) {
            setWsStatus("reconnecting");
            reconnectTimer = window.setTimeout(connect, 2800);
          }
        };
      } catch {
        setWsStatus("reconnecting");
        reconnectTimer = window.setTimeout(connect, 2800);
      }
    };

    connect();
    return () => {
      closedByApp = true;
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  const forecastRows: Record<string, any>[] = forecastResponse?.forecast ?? [];
  const dispatchRows: Record<string, any>[] = dispatchResponse?.dispatch ?? [];
  const resilienceRows: Record<string, any>[] = resilience?.schedule ?? [];
  const dailyRows: Record<string, any>[] = financialHistory?.daily ?? [];
  const battery = telemetry?.battery ?? {};
  const batterySnapshot = battery.representative_snapshot ?? {};
  const current = metrics?.current ?? dispatchRows[0] ?? {};
  const financial = financialHistory?.summary ?? {};
  const gridAvailable = health?.grid_available ?? state?.grid_available ?? true;
  const currentMode = health?.mode ?? dispatchResponse?.mode ?? "CONNECTING";
  const solarNow = current.solar_kw ?? forecastRows[0]?.predicted_solar_kw;
  const loadNow = current.load_kw ?? forecastRows[0]?.predicted_load_kw;
  const batterySoc = current.battery_soc_kwh ?? batterySnapshot.battery_soc_kwh;
  const batterySocPct = batterySnapshot.battery_soc_pct ?? (Number(batterySoc) / 1000) * 100;
  const forecastMetrics = forecastResponse?.metrics ?? state?.forecast_metrics ?? {};
  const socketIsLive = wsStatus === "connected";
  const co2Avoided = sustainability?.estimated_co2_avoided_kg;
  const renewablePct = sustainability?.renewable_utilization_pct;
  const resilienceScore = resilience?.resilience_score;

  const energyChart = useMemo(() => forecastRows.map((row, index) => ({
    time: timeLabel(row, index),
    Solar: Number(row.predicted_solar_kw ?? 0),
    Load: Number(row.predicted_load_kw ?? 0),
  })), [forecastRows]);

  const dispatchChart = useMemo(() => dispatchRows.map((row, index) => ({
    time: timeLabel(row, index),
    "Grid import": Number(row.grid_import_kw ?? 0),
    "Charge": Number(row.battery_charge_kw ?? 0),
    "Discharge": Number(row.battery_discharge_kw ?? 0),
    "Battery SOC": Number(row.battery_soc_kwh ?? 0),
  })), [dispatchRows]);

  const financialChart = useMemo(() => dailyRows.map((row) => ({
    date: String(row.date ?? "").slice(5),
    fullDate: row.date,
    "Without optimization": Number(row.cost_without_ai_rs ?? 0),
    "Solar-aware estimate": Number(row.cost_with_ai_rs ?? 0),
  })), [dailyRows]);

  const resilienceChart = useMemo(() => resilienceRows.map((row, index) => ({
    time: timeLabel(row, index),
    "Critical served": Number(row.critical_served_kw ?? 0),
    "Critical unserved": Number(row.critical_unserved_kw ?? 0),
    "Non-critical served": Number(row.noncritical_served_kw ?? 0),
  })), [resilienceRows]);

  const lastUpdated = liveSnapshot?.timestamp
    ? new Date(liveSnapshot.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : health?.timestamp
      ? new Date(health.timestamp).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
      : "Waiting for API";
  const currentDate = new Date().toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });

  const navigateTo = (id: string) => {
    setActiveNav(id);
    setSidebarOpen(false);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const runAction = async (action: string, label: string) => {
    setBusyAction(action);
    setToast(null);
    try {
      const response = await apiPost<Record<string, any>>(`/simulate/${action}`);
      await refreshData();
      setToast({ type: "success", message: response.message ?? `${label} complete.` });
    } catch (error) {
      setToast({
        type: "error",
        message: error instanceof Error ? error.message : `Could not run ${label.toLowerCase()}.`,
      });
    } finally {
      setBusyAction(null);
    }
  };

  const chartTooltipStyle = {
    backgroundColor: theme === "dark" ? "#17211f" : "#ffffff",
    border: `1px solid ${theme === "dark" ? "#293a34" : "#dfe8e2"}`,
    borderRadius: "12px",
    color: theme === "dark" ? "#f1f7f2" : "#15231c",
    fontSize: 12,
    boxShadow: "0 12px 32px rgba(0,0,0,.12)",
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? "sidebar-open" : ""}`}>
        <div className="brand-row">
          <div className="brand-mark"><Zap size={22} fill="currentColor" strokeWidth={2.3} /></div>
          <div className="brand-copy">
            <span className="brand-name">voltforge<span className="brand-period">.</span></span>
            <span className="brand-subtitle">ENERGY INTELLIGENCE</span>
          </div>
          <button className="icon-button mobile-close" aria-label="Close navigation" onClick={() => setSidebarOpen(false)}><X size={18} /></button>
        </div>

        <div className="workspace-switcher">
          <div className="workspace-avatar"><Grid2X2 size={18} /></div>
          <div className="workspace-copy"><strong>Campus Microgrid</strong><span>Primary site · India</span></div>
          <ChevronDown size={15} className="muted-icon" />
        </div>

        <p className="sidebar-label">WORKSPACE</p>
        <nav className="sidebar-nav" aria-label="Main navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button key={item.id} className={`nav-link ${activeNav === item.id ? "active" : ""}`} onClick={() => navigateTo(item.id)}>
                <Icon size={18} strokeWidth={1.9} />
                <span>{item.label}</span>
                {item.id === "resilience" && <span className="nav-status-dot" />}
              </button>
            );
          })}
        </nav>

        <p className="sidebar-label sidebar-label-spaced">SYSTEM</p>
        <button className="nav-link" onClick={() => void refreshData()}>
          <SlidersHorizontal size={18} strokeWidth={1.9} />
          <span>Refresh all data</span>
          <RefreshCw size={14} className={refreshing ? "spin muted-icon" : "muted-icon"} />
        </button>

        <div className="sidebar-spacer" />
        <div className="sidebar-health">
          <div className="sidebar-health-top">
            <span className="pulse-dot" />
            <span>{gridAvailable ? "Grid connected" : "Island mode active"}</span>
            <span className="health-live">{gridAvailable ? "LIVE" : "EVENT"}</span>
          </div>
          <div className="sidebar-health-meter"><span style={{ width: `${Math.max(8, Number(resilienceScore ?? 100))}%` }} /></div>
          <div className="sidebar-health-bottom"><span>Resilience index</span><strong>{resilienceScore === undefined ? "—" : `${number(resilienceScore)} / 100`}</strong></div>
        </div>
        <div className="sidebar-user">
          <div className="user-avatar">VF</div>
          <div className="user-copy"><strong>VoltForge Ops</strong><span>Control room</span></div>
          <ChevronDown size={15} className="muted-icon" />
        </div>
      </aside>

      <AnimatePresence>
        {sidebarOpen && <motion.button className="sidebar-scrim" aria-label="Close navigation" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setSidebarOpen(false)} />}
      </AnimatePresence>

      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-left">
            <button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}><Menu size={19} /></button>
            <div className="breadcrumbs"><span>VoltForge</span><ChevronRight size={14} /><strong>{navItems.find((item) => item.id === activeNav)?.label ?? "Overview"}</strong></div>
          </div>
          <div className="topbar-right">
            <div className="date-pill"><CalendarDays size={15} /><span>{currentDate}</span></div>
            <div className={`connection-pill ${apiConnected ? "connected" : "disconnected"}`}>
              <span className="connection-dot" />
              <span>{apiConnected ? "API online" : "API offline"}</span>
            </div>
            <button className="icon-button" aria-label="Refresh all dashboard data" title="Refresh data" onClick={() => void refreshData()} disabled={refreshing}>
              <RefreshCw size={17} className={refreshing ? "spin" : ""} />
            </button>
            <button className="theme-toggle" aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              <AnimatePresence mode="wait" initial={false}>
                <motion.span key={theme} initial={{ opacity: 0, rotate: -45, scale: 0.6 }} animate={{ opacity: 1, rotate: 0, scale: 1 }} exit={{ opacity: 0, rotate: 45, scale: 0.6 }} transition={{ duration: 0.18 }}>
                  {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
                </motion.span>
              </AnimatePresence>
            </button>
            <button className="notification-button icon-button" aria-label="Notifications" title="System notifications"><Bell size={17} /><i /></button>
          </div>
        </header>

        <main className="dashboard-main">
          <section className="welcome-row" id="overview">
            <div className="welcome-copy">
              <div className="eyebrow welcome-eyebrow"><span className="eyebrow-line" />MICROGRID OPERATIONS <span className="eyebrow-divider">/</span> CONTROL CENTER</div>
              <h1>Energy in <span>balance.</span></h1>
              <p>One clear view of your microgrid. Forecast demand, orchestrate storage, and keep critical systems resilient.</p>
              <div className="welcome-meta">
                <span className="live-indicator"><span className="pulse-dot" />Live monitoring</span>
                <span className="meta-separator" />
                <span className="updated-copy">Last signal {lastUpdated}</span>
              </div>
            </div>
            <motion.div className="hero-orbit" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.7, ease: "easeOut" }}>
              <div className="orbit orbit-one" /><div className="orbit orbit-two" /><div className="orbit orbit-three" />
              <motion.div className="orbit-core" animate={{ boxShadow: ["0 0 24px rgba(105,226,156,.14)", "0 0 44px rgba(105,226,156,.30)", "0 0 24px rgba(105,226,156,.14)"] }} transition={{ duration: 3.2, repeat: Infinity }}>
                <Zap size={33} fill="currentColor" />
              </motion.div>
              <span className="orbit-node orbit-node-a"><Sun size={15} /></span>
              <span className="orbit-node orbit-node-b"><BatteryCharging size={15} /></span>
              <span className="orbit-node orbit-node-c"><Activity size={15} /></span>
            </motion.div>
          </section>

          {apiError && (
            <motion.div className="api-warning" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}>
              <AlertTriangle size={17} />
              <div><strong>{apiError}</strong><span>Dashboard sections with available data remain usable. Check the backend terminal if these errors persist.</span></div>
              <button onClick={() => void refreshData()}>Retry <RefreshCw size={14} /></button>
            </motion.div>
          )}

          <section className="overview-section">
            <SectionHeading
              eyebrow="AT A GLANCE"
              title="Live overview"
              detail="Current operating snapshot and forecast-led indicators."
              right={<span className="simulation-tag"><CircleDot size={12} /> SIMULATION DATA</span>}
            />
            <div className="metrics-grid">
              <MetricCard label="Solar generation" value={number(solarNow, 1)} unit="kW" icon={Sun} tone="tone-solar" foot="Forecast · current slot" delay={0.04} line={[18, 24, 21, 37, 44, 39, 54]} />
              <MetricCard label="Campus demand" value={number(loadNow, 1)} unit="kW" icon={Activity} tone="tone-load" foot="Forecast · current slot" delay={0.1} line={[42, 37, 49, 44, 58, 53, 61]} />
              <MetricCard label="Battery charge" value={number(batterySoc, 0)} unit="kWh" icon={BatteryCharging} tone="tone-battery" foot={`${number(batterySocPct, 1)}% estimated state of charge`} delay={0.16} line={[63, 58, 67, 62, 74, 70, 79]} />
              <MetricCard label="30-day savings" value={financial.estimated_savings_rs === undefined ? "—" : money(financial.estimated_savings_rs)} icon={TrendingUp} tone="tone-savings" foot={`${number(financial.estimated_savings_pct, 2)}% indicative reduction`} trend="simulated" delay={0.22} line={[21, 25, 33, 31, 45, 53, 64]} />
            </div>
          </section>

          <section className="content-grid chart-row">
            <motion.article className="panel chart-panel energy-panel" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.24, duration: 0.45 }}>
              <div className="panel-header">
                <div><div className="panel-title-row"><span className="panel-icon panel-icon-green"><Activity size={16} /></span><h3>Energy forecast</h3><span className="subtle-live"><span />NEXT 24 HOURS</span></div><p>Predicted solar generation against site demand</p></div>
                <div className="chart-legend"><span><i className="legend-dot solar-dot" />Solar</span><span><i className="legend-dot load-dot" />Demand</span></div>
              </div>
              {energyChart.length ? (
                <div className="chart-area energy-chart">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={energyChart} margin={{ top: 10, right: 4, left: -18, bottom: 0 }}>
                      <defs>
                        <linearGradient id="solarFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#78e5a4" stopOpacity={0.32} /><stop offset="95%" stopColor="#78e5a4" stopOpacity={0.015} /></linearGradient>
                        <linearGradient id="loadFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#8ba8ff" stopOpacity={0.18} /><stop offset="95%" stopColor="#8ba8ff" stopOpacity={0.01} /></linearGradient>
                      </defs>
                      <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                      <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 10 }} interval={3} />
                      <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 10 }} width={45} />
                      <Tooltip contentStyle={chartTooltipStyle} formatter={(value: number | string) => [`${number(value, 1)} kW`]} />
                      <Area type="monotone" dataKey="Solar" stroke="#79e5a4" strokeWidth={2.4} fill="url(#solarFill)" activeDot={{ r: 4, strokeWidth: 0 }} isAnimationActive />
                      <Area type="monotone" dataKey="Load" stroke="#8ba8ff" strokeWidth={2.2} fill="url(#loadFill)" activeDot={{ r: 4, strokeWidth: 0 }} isAnimationActive />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : <EmptyChart message="Waiting for forecast data from the API…" />}
              <div className="chart-footnote"><span><span className="mini-status-dot" />XGBoost forecast</span><span>MAE: solar {number(forecastMetrics.solar_mae, 2)} kW · load {number(forecastMetrics.load_mae, 2)} kW</span></div>
            </motion.article>

            <motion.article className="panel status-panel" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3, duration: 0.45 }}>
              <div className="panel-header"><div><div className="panel-title-row"><span className="panel-icon panel-icon-blue"><Gauge size={16} /></span><h3>Grid status</h3></div><p>System operating conditions</p></div><span className={`status-badge ${gridAvailable ? "status-healthy" : "status-warning"}`}><span />{gridAvailable ? "HEALTHY" : "ISLANDED"}</span></div>
              <div className="status-hero">
                <div className={`status-illustration ${gridAvailable ? "" : "status-illustration-warning"}`}>
                  <div className="status-illustration-ring" /><div className="status-illustration-ring inner" />
                  {gridAvailable ? <Power size={29} /> : <ShieldCheck size={29} />}
                </div>
                <div className="status-hero-copy"><span>Operating mode</span><strong>{String(currentMode).replaceAll("_", " ")}</strong><small>{gridAvailable ? "Grid connection available" : "Grid unavailable · island operation"}</small></div>
              </div>
              <div className="status-stats">
                <div><span>Grid import</span><strong>{number(current.grid_import_kw ?? dispatchRows[0]?.grid_import_kw, 1)} <small>kW</small></strong></div>
                <div><span>Retail tariff</span><strong>₹{number(current.tariff_rs_per_kwh ?? forecastRows[0]?.tariff_rs_per_kwh, 2)} <small>/kWh</small></strong></div>
                <div><span>Socket stream</span><strong className="socket-state">{socketIsLive ? <><Wifi size={14} /> Connected</> : <><WifiOff size={14} /> {wsStatus}</>}</strong></div>
              </div>
              <div className="status-panel-bottom"><span><span className="mini-status-dot" />Automatic refresh every 20 seconds</span><span>{lastPulse ? "Live pulse received" : "Awaiting live pulse"}</span></div>
            </motion.article>
          </section>

          <section id="dispatch" className="dashboard-section">
            <SectionHeading eyebrow="POWER FLOW" title="Energy dispatch" detail="Optimized grid imports and battery scheduling across the 24-hour horizon." right={<span className="section-chip"><Cpu size={13} /> SCIPY MILP OPTIMIZER</span>} />
            <div className="content-grid dispatch-grid">
              <article className="panel dispatch-panel">
                <div className="panel-header">
                  <div><div className="panel-title-row"><span className="panel-icon panel-icon-violet"><Zap size={16} /></span><h3>Dispatch schedule</h3></div><p>Grid exchange and battery power by hour</p></div>
                  <div className="chart-legend dispatch-legend"><span><i className="legend-dot grid-dot" />Grid</span><span><i className="legend-dot charge-dot" />Charge</span><span><i className="legend-dot discharge-dot" />Discharge</span></div>
                </div>
                {dispatchChart.length ? (
                  <div className="chart-area dispatch-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={dispatchChart} margin={{ top: 8, right: 6, left: -18, bottom: 0 }} barGap={2}>
                        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                        <XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 10 }} interval={3} />
                        <YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 10 }} width={45} />
                        <Tooltip contentStyle={chartTooltipStyle} formatter={(value: number | string) => [`${number(value, 1)} kW`]} />
                        <Bar dataKey="Grid import" fill="#91a9fb" radius={[3, 3, 0, 0]} maxBarSize={12} isAnimationActive />
                        <Bar dataKey="Charge" fill="#79e5a4" radius={[3, 3, 0, 0]} maxBarSize={12} isAnimationActive />
                        <Bar dataKey="Discharge" fill="#f3b86a" radius={[3, 3, 0, 0]} maxBarSize={12} isAnimationActive />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : <EmptyChart message="Dispatch will appear after the API responds." />}
                <div className="dispatch-summary">
                  <div><span className="summary-mark mark-blue" /><span>Grid import</span><strong>{number(dispatchRows.reduce((sum, row) => sum + Number(row.grid_import_kw ?? 0), 0), 1)} <small>kWh*</small></strong></div>
                  <div><span className="summary-mark mark-green" /><span>Solar energy used</span><strong>{number(sustainability?.renewable_energy_utilized_kwh, 1)} <small>kWh*</small></strong></div>
                  <div><span className="summary-mark mark-orange" /><span>Solar curtailed</span><strong>{number(sustainability?.solar_curtailed_kwh, 1)} <small>kWh*</small></strong></div>
                </div>
                <p className="micro-disclaimer">*Indicative 1-hour timestep totals over the forecast horizon.</p>
              </article>

              <article className="panel battery-panel">
                <div className="panel-header"><div><div className="panel-title-row"><span className="panel-icon panel-icon-green"><BatteryCharging size={16} /></span><h3>Battery intelligence</h3></div><p>Storage capacity and estimated condition</p></div><span className="small-tag">MODEL ESTIMATE</span></div>
                <div className="battery-gauge-wrap">
                  <div className="battery-gauge" style={{ "--soc": `${Math.min(100, Math.max(0, Number(batterySocPct) || 0))}%` } as CSSProperties}>
                    <div className="gauge-inner"><BatteryCharging size={25} /><strong>{number(batterySocPct, 1)}<small>%</small></strong><span>STATE OF CHARGE</span></div>
                  </div>
                  <div className="battery-gauge-side"><span>Available energy</span><strong>{number(batterySoc, 1)} <small>kWh</small></strong><div className="battery-scale"><span style={{ width: `${Math.min(100, Math.max(0, Number(batterySocPct) || 0))}%` }} /></div><div className="battery-limits"><span>0 kWh</span><span>1,000 kWh</span></div><div className="battery-reserve"><ShieldCheck size={14} /><span>Minimum reserve: 100 kWh</span></div></div>
                </div>
                <div className="battery-details">
                  <div className="battery-detail-item"><span><Thermometer size={14} /> Estimated temperature</span><strong>{number(batterySnapshot.estimated_battery_temperature_c, 1)}°C</strong><small>Range {number(battery.estimated_temperature_min_c, 1)}–{number(battery.estimated_temperature_max_c, 1)}°C</small></div>
                  <div className="battery-detail-item"><span><Activity size={14} /> Estimated health</span><strong>{number(battery.estimated_health_pct_after_horizon, 3)}%</strong><small>{number(battery.equivalent_full_cycles_over_horizon, 3)} equivalent cycles</small></div>
                </div>
                <div className="notice-box"><AlertTriangle size={15} /><span>Illustrative model estimates only. No physical battery sensors are connected.</span></div>
              </article>
            </div>
          </section>

          <section id="resilience" className="dashboard-section">
            <SectionHeading eyebrow="STRESS TESTING" title="Resilience lab" detail="Inject a simulated event and observe how the dispatch engine responds." right={<span className="section-chip"><ShieldCheck size={13} /> CRITICAL LOAD PRIORITY</span>} />
            <div className="content-grid resilience-grid">
              <article className="panel simulator-panel">
                <div className="panel-header"><div><div className="panel-title-row"><span className="panel-icon panel-icon-orange"><Wind size={16} /></span><h3>Scenario controls</h3></div><p>Safe software simulations — no physical equipment is controlled</p></div><span className="small-tag">INTERACTIVE</span></div>
                <div className="scenario-grid">
                  <button className={`scenario-card scenario-cloud ${busyAction === "cloud" ? "scenario-busy" : ""}`} disabled={Boolean(busyAction)} onClick={() => void runAction("cloud", "Cloud cover simulation")}>
                    <div className="scenario-icon"><CloudSun size={21} /></div><div className="scenario-copy"><strong>Cloud cover</strong><span>Reduce expected solar generation</span></div><ChevronRight size={17} />
                    <span className="scenario-action">{busyAction === "cloud" ? "Applying…" : "Simulate event"}</span>
                  </button>
                  <button className={`scenario-card scenario-load ${busyAction === "load-spike" ? "scenario-busy" : ""}`} disabled={Boolean(busyAction)} onClick={() => void runAction("load-spike", "Load spike simulation")}>
                    <div className="scenario-icon"><TrendingUp size={21} /></div><div className="scenario-copy"><strong>Load spike</strong><span>Increase forecast demand by 35%</span></div><ChevronRight size={17} />
                    <span className="scenario-action">{busyAction === "load-spike" ? "Applying…" : "Simulate event"}</span>
                  </button>
                  <button className={`scenario-card scenario-blackout ${busyAction === "blackout" ? "scenario-busy" : ""}`} disabled={Boolean(busyAction)} onClick={() => void runAction("blackout", "Grid blackout simulation")}>
                    <div className="scenario-icon"><Power size={21} /></div><div className="scenario-copy"><strong>Grid blackout</strong><span>Force island operation for the horizon</span></div><ChevronRight size={17} />
                    <span className="scenario-action">{busyAction === "blackout" ? "Switching…" : "Simulate event"}</span>
                  </button>
                  <button className={`scenario-card scenario-restore ${busyAction === "restore" ? "scenario-busy" : ""}`} disabled={Boolean(busyAction)} onClick={() => void runAction("restore", "Grid restoration")}>
                    <div className="scenario-icon"><RefreshCw size={21} /></div><div className="scenario-copy"><strong>Restore grid</strong><span>Return to normal optimized mode</span></div><ChevronRight size={17} />
                    <span className="scenario-action">{busyAction === "restore" ? "Restoring…" : "Restore operation"}</span>
                  </button>
                </div>
                <div className="scenario-footer"><span><CheckCircle2 size={14} /> Simulation endpoint connected</span><span>Changes are in-memory until the API restarts</span></div>
              </article>

              <article className="panel resilience-panel">
                <div className="panel-header"><div><div className="panel-title-row"><span className="panel-icon panel-icon-green"><ShieldCheck size={16} /></span><h3>Critical load protection</h3></div><p>Resilience score across the 24-hour scenario</p></div><span className={`status-badge ${Number(resilienceScore ?? 0) >= 90 ? "status-healthy" : "status-warning"}`}><span />{Number(resilienceScore ?? 0) >= 90 ? "STRONG" : "MONITOR"}</span></div>
                <div className="resilience-score-wrap">
                  <div className="resilience-score"><svg viewBox="0 0 180 110" role="img" aria-label={`Resilience score ${number(resilienceScore)}`}><path d="M 18 94 A 72 72 0 0 1 162 94" fill="none" stroke="var(--gauge-track)" strokeWidth="13" strokeLinecap="round" /><motion.path d="M 18 94 A 72 72 0 0 1 162 94" fill="none" stroke="url(#resilienceGradient)" strokeWidth="13" strokeLinecap="round" pathLength="100" initial={{ strokeDasharray: "0 100" }} animate={{ strokeDasharray: `${Math.min(100, Math.max(0, Number(resilienceScore ?? 0)))} 100` }} transition={{ duration: 1.1, ease: "easeOut" }} /><defs><linearGradient id="resilienceGradient" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stopColor="#f1ba6d" /><stop offset="100%" stopColor="#78e5a4" /></linearGradient></defs></svg><div className="resilience-score-copy"><strong>{resilienceScore === undefined ? "—" : number(resilienceScore)}<small>/100</small></strong><span>RESILIENCE INDEX</span></div></div>
                  <div className="resilience-score-details"><div><span className="score-dot score-green" /><span>Critical loads have highest priority</span></div><div><span className="score-dot score-blue" /><span>Outage window modeled at 18:00–21:00 in scheduled scenario</span></div><div><span className="score-dot score-orange" /><span>Non-critical demand may be shed</span></div></div>
                </div>
                <div className="resilience-chart-head"><strong>Critical load served</strong><span>kW by hour</span></div>
                {resilienceChart.length ? <div className="chart-area resilience-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={resilienceChart} margin={{ top: 8, right: 3, left: -20, bottom: 0 }}><defs><linearGradient id="criticalFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#79e5a4" stopOpacity={0.25} /><stop offset="100%" stopColor="#79e5a4" stopOpacity={0.01} /></linearGradient></defs><CartesianGrid stroke="var(--chart-grid)" vertical={false} /><XAxis dataKey="time" tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 9 }} interval={5} /><YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 9 }} width={42} /><Tooltip contentStyle={chartTooltipStyle} formatter={(value: number | string) => [`${number(value, 1)} kW`]} /><Area type="monotone" dataKey="Critical served" stroke="#79e5a4" fill="url(#criticalFill)" strokeWidth={2} isAnimationActive /><Area type="monotone" dataKey="Critical unserved" stroke="#f3b86a" fill="#f3b86a" fillOpacity={0.08} strokeWidth={1.8} isAnimationActive /></AreaChart></ResponsiveContainer></div> : <EmptyChart message="Resilience schedule is loading." />}
                <p className="micro-disclaimer">A 100/100 score means full critical-load coverage in the current model—not guaranteed service to every load in a real outage.</p>
              </article>
            </div>
          </section>

          <section id="insights" className="dashboard-section last-section">
            <SectionHeading eyebrow="PERFORMANCE & PURPOSE" title="Insights that matter" detail="Indicative financial performance and sustainability for the current simulation." right={<span className="section-chip"><Sparkles size={13} /> MODEL-DERIVED</span>} />
            <div className="content-grid insights-grid">
              <article className="panel financial-panel">
                <div className="panel-header"><div><div className="panel-title-row"><span className="panel-icon panel-icon-violet"><TrendingUp size={16} /></span><h3>Financial performance</h3></div><p>Last 30 completed days · INR</p></div><span className="small-tag">{financialHistory?.period_start ?? "—"} — {financialHistory?.period_end ?? "—"}</span></div>
                <div className="financial-big-number"><div><span>Estimated savings</span><strong>{financial.estimated_savings_rs === undefined ? "—" : money(financial.estimated_savings_rs)}</strong></div><div className="savings-percent"><ArrowDownRight size={16} /><strong>{number(financial.estimated_savings_pct, 2)}%</strong><span>indicative reduction</span></div></div>
                {financialChart.length ? <div className="chart-area financial-chart"><ResponsiveContainer width="100%" height="100%"><AreaChart data={financialChart} margin={{ top: 10, right: 3, left: -15, bottom: 0 }}><defs><linearGradient id="baselineFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#93a9fb" stopOpacity={0.20} /><stop offset="100%" stopColor="#93a9fb" stopOpacity={0.01} /></linearGradient><linearGradient id="solarAwareFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#79e5a4" stopOpacity={0.22} /><stop offset="100%" stopColor="#79e5a4" stopOpacity={0.01} /></linearGradient></defs><CartesianGrid stroke="var(--chart-grid)" vertical={false} /><XAxis dataKey="date" tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 9 }} interval={4} /><YAxis tickLine={false} axisLine={false} tick={{ fill: "var(--chart-label)", fontSize: 9 }} width={48} tickFormatter={(value: number) => value >= 1000 ? `₹${(value / 1000).toFixed(0)}k` : `₹${value}`} /><Tooltip contentStyle={chartTooltipStyle} labelFormatter={(_, payload) => payload?.[0]?.payload?.fullDate ?? ""} formatter={(value) => [money(Number(value))]} /><Area type="monotone" dataKey="Without optimization" stroke="#93a9fb" fill="url(#baselineFill)" strokeWidth={1.8} isAnimationActive /><Area type="monotone" dataKey="Solar-aware estimate" stroke="#79e5a4" fill="url(#solarAwareFill)" strokeWidth={2} isAnimationActive /></AreaChart></ResponsiveContainer></div> : <EmptyChart message="Financial history is loading." />}
                <div className="financial-legend"><span><i className="legend-dot load-dot" />Cost without solar offset</span><span><i className="legend-dot solar-dot" />Solar-aware estimate</span></div>
                <div className="notice-box notice-neutral"><AlertTriangle size={15} /><span>Synthetic historical simulation; not metered billing data or a replay of 30 optimized schedules.</span></div>
              </article>

              <article className="panel impact-panel">
                <div className="panel-header"><div><div className="panel-title-row"><span className="panel-icon panel-icon-green"><Leaf size={16} /></span><h3>Sustainability impact</h3></div><p>Forecast-horizon renewable metrics</p></div><span className="small-tag">24-HOUR ESTIMATE</span></div>
                <div className="impact-hero">
                  <div className="impact-icon-wrap"><Leaf size={25} /></div>
                  <div><strong>{number(co2Avoided, 1)} <small>kg CO₂</small></strong><span>Estimated emissions avoided</span></div>
                </div>
                <div className="impact-progress-block"><div className="impact-progress-label"><span>Renewable utilization</span><strong>{number(renewablePct, 1)}%</strong></div><div className="impact-progress"><span style={{ width: `${Math.min(100, Math.max(0, Number(renewablePct) || 0))}%` }} /></div><div className="impact-progress-caption"><span>Renewable generation utilized</span><span>{number(sustainability?.renewable_energy_utilized_kwh, 1)} kWh*</span></div></div>
                <div className="impact-stats"><div><Sun size={15} /><span>Solar generated</span><strong>{number(sustainability?.renewable_generation_forecast_kwh, 1)} <small>kWh*</small></strong></div><div><Wind size={15} /><span>Solar curtailed</span><strong>{number(sustainability?.solar_curtailed_kwh, 1)} <small>kWh*</small></strong></div><div><Zap size={15} /><span>Grid imported</span><strong>{number(sustainability?.grid_import_kwh, 1)} <small>kWh*</small></strong></div></div>
                <div className="notice-box"><AlertTriangle size={15} /><span>Indicative estimate using a configurable grid-emissions factor. Not metered or lifecycle carbon accounting.</span></div>
              </article>
            </div>
          </section>

          <footer className="dashboard-footer"><div className="footer-brand"><span className="footer-mark"><Zap size={14} fill="currentColor" /></span><strong>voltforge<span>.</span></strong><span>Build a more resilient energy future.</span></div><div className="footer-meta"><span><span className="mini-status-dot" /> API {apiConnected ? "connected" : "disconnected"}</span><span>WebSocket {wsStatus}</span><span>Last refresh {lastUpdated}</span></div><p>Forecasts, savings, carbon impact and battery health are software-model estimates from synthetic data unless otherwise stated.</p></footer>
        </main>
      </div>

      <AnimatePresence>
        {toast && (
          <motion.div className={`toast toast-${toast.type}`} role="status" initial={{ opacity: 0, y: 16, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: 10, scale: 0.98 }} transition={{ duration: 0.22 }}>
            {toast.type === "success" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
            <span>{toast.message}</span>
            <button aria-label="Dismiss notification" onClick={() => setToast(null)}><X size={16} /></button>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default App;
