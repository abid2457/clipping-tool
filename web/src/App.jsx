import { useEffect, useState, useRef, useCallback } from "react";
import { api, streamProgress } from "./api.js";
import { Icons } from "./components/Icons.jsx";
import logoImg from "./assets/logo.jpg";
import Create from "./pages/Create.jsx";
import Library from "./pages/Library.jsx";
import Settings from "./pages/Settings.jsx";
import OneClickAI from "./pages/OneClickAI.jsx";
import AutoAgent from "./pages/AutoAgent.jsx";
import PublishingQueue from "./pages/PublishingQueue.jsx";
import YouTubeDashboard from "./pages/YouTubeDashboard.jsx";

const NAV = [
  { id: "oneclick", label: "One-Click AI", icon: Icons.bolt || Icons.create },
  { id: "create", label: "Manual Wizard", icon: Icons.create },
  { id: "agent", label: "Auto Agent", icon: Icons.settings },
  { id: "queue", label: "Publish Queue", icon: Icons.library },
  { id: "channels", label: "Channels", icon: Icons.library },
  { id: "library", label: "Library", icon: Icons.library },
  { id: "settings", label: "Settings", icon: Icons.settings },
];

const TITLES = {
  oneclick: { h: "One-Click AI Studio", sub: "Autonomous hook discovery, smart reframing & instant Shorts generation" },
  create: { h: "Manual Wizard", sub: "7-step precision editor for custom captions, kinetic typography & reframing" },
  agent: { h: "Auto Agent", sub: "Autonomous channel monitor & local watched-directory sync" },
  queue: { h: "Publishing Queue", sub: "Review AI scores, refine viral metadata & publish directly to YouTube" },
  channels: { h: "YouTube Channels", sub: "Google OAuth 2.0 authorization & real-time quota telemetry" },
  library: { h: "Media Library", sub: "All generated short-form clips & long-form exports" },
  settings: { h: "Application Settings", sub: "Hardware compute preferences, AI models & environment configuration" },
};

const THEMES = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
];

// First-run (and every relaunch, briefly) splash while the whisper model
// loads. On a fresh install this can take a few minutes to download — this
// screen is the fix for that looking "stuck": real progress instead of a
// refused connection or a blank tab.
function ModelSplash({ status }) {
  const pct = status.progress != null ? Math.round(status.progress * 100) : null;
  const failed = status.status === "error";
  return (
    <div className="model-splash">
      <div className="model-splash-mark">
        <img src={logoImg} alt="Tech Hub" />
      </div>
      <div className="model-splash-title">Tech Hub</div>
      <div className="model-splash-by">Created by Barakah Tech</div>
      {failed ? (
        <>
          <div className="model-splash-msg" style={{ color: "var(--danger)" }}>Could not start the AI engine.</div>
          <div className="model-splash-detail">{status.message}</div>
          <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => window.location.reload()}>Retry</button>
        </>
      ) : (
        <>
          <div className="model-splash-msg">{status.message || "Initializing AI engine…"}</div>
          <div className="track model-splash-track">
            <div className={"fill" + (pct == null ? " indeterminate" : "")} style={pct == null ? {} : { width: pct + "%" }} />
          </div>
          {status.status === "downloading" && (
            <div className="model-splash-detail">One-time download — this machine won't need it again.</div>
          )}
        </>
      )}
    </div>
  );
}

// Segmented light/dark switch. Writes the choice to <html data-theme> and
// remembers it across reloads. "dark" is the CSS default, so we clear the attr.
function ThemeSwitch({ theme, setTheme, fixed }) {
  return (
    <div className={"theme-switch" + (fixed ? " theme-switch-fixed" : "")} role="group" aria-label="Theme">
      {THEMES.map((t) => (
        <button key={t.id} className={theme === t.id ? "active" : ""}
          onClick={() => setTheme(t.id)} title={`${t.label} theme`}>{t.label}</button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActiveJobDock — persistent floating widget that shows active job progress
// globally, even when user switches between sidebar tabs.
// ---------------------------------------------------------------------------
function ActiveJobDock({ job, onPause, onResume, onCancel, onRetry, onNavigate }) {
  if (!job) return null;

  const st = job.status;
  const isRunning = st === "running" || st === "queued" || st === "pending";
  const isPaused = st === "paused";
  const isDone = st === "done";
  const isError = st === "error";
  const isCancelled = st === "cancelled";

  // Auto-hide done/error/cancelled after 15 seconds
  if (isDone || isError || isCancelled) {
    // We handle the timeout in the parent — just render it.
  }

  const pct = job.progress != null ? Math.round(job.progress * 100) : 0;

  const statusLabel = {
    running: "Processing",
    paused: "Paused",
    done: "Complete",
    error: "Error",
    cancelled: "Cancelled",
    queued: "Queued",
    pending: "Starting",
  }[st] || st;

  const statusClass = {
    running: "dock-running",
    paused: "dock-paused",
    done: "dock-done",
    error: "dock-error",
    cancelled: "dock-cancelled",
    queued: "dock-running",
    pending: "dock-running",
  }[st] || "";

  return (
    <div className={`active-job-dock ${statusClass}`}>
      <div className="dock-top">
        <div className="dock-status-row">
          <span className={`dock-pulse ${isRunning ? "pulse-active" : ""}`} />
          <span className="dock-status-label">{statusLabel}</span>
          <span className="dock-pct">{isRunning || isPaused ? `${pct}%` : ""}</span>
        </div>
        <button className="dock-nav-btn" onClick={onNavigate} title="Open in Studio">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>
          </svg>
        </button>
      </div>

      {(isRunning || isPaused) && (
        <div className="dock-track">
          <div className="dock-fill" style={{ width: `${pct}%` }} />
        </div>
      )}

      <div className="dock-msg">{job.message || "Video pipeline active"}</div>

      <div className="dock-actions">
        {isRunning && (
          <button className="dock-btn dock-btn-pause" onClick={onPause} title="Pause">⏸ Pause</button>
        )}
        {isPaused && (
          <button className="dock-btn dock-btn-resume" onClick={onResume} title="Resume">▶ Resume</button>
        )}
        {(isRunning || isPaused) && (
          <button className="dock-btn dock-btn-cancel" onClick={onCancel} title="Cancel">✕ Cancel</button>
        )}
        {isError && (
          <button className="dock-btn dock-btn-retry" onClick={onRetry} title="Retry from Checkpoint">↻ Retry</button>
        )}
      </div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState("create");
  const [step, setStep] = useState(1);
  const [device, setDevice] = useState(null);
  const [online, setOnline] = useState(null);
  const [navOpen, setNavOpen] = useState(false);
  const [theme, setTheme] = useState(() => {
    try { return localStorage.getItem("cf-theme") || "dark"; } catch { return "dark"; }
  });
  const [modelStatus, setModelStatus] = useState({ status: "idle", message: "", progress: null });

  // Global active-job state for the floating dock
  const [dockJob, setDockJob] = useState(null);
  const dockStreamRef = useRef(null);
  const dockDismissTimer = useRef(null);

  // Fetch active job on mount + tab-switch + poll interval
  const pollActiveJob = useCallback(async () => {
    try {
      const res = await api.activeJob();
      if (res.has_active_job && res.job) {
        setDockJob(res.job);
        // If running/paused, subscribe to live stream updates
        const jst = res.job.status;
        if ((jst === "running" || jst === "paused" || jst === "queued" || jst === "pending") && dockStreamRef.current === null) {
          dockStreamRef.current = streamProgress(
            res.job.id,
            (snap) => {
              setDockJob((prev) => ({ ...(prev || {}), ...snap }));
              if (snap.status === "done" || snap.status === "error" || snap.status === "cancelled") {
                // Auto-dismiss dock after 12 seconds for terminal states
                clearTimeout(dockDismissTimer.current);
                dockDismissTimer.current = setTimeout(() => setDockJob(null), 12000);
              }
            },
            () => { /* stream error — will reconnect automatically */ }
          );
        }
      } else {
        // No active job — only clear if dock is showing a terminal state
        setDockJob((prev) => {
          if (!prev) return null;
          if (prev.status === "running" || prev.status === "paused") return prev; // keep — may be lag
          return prev; // keep terminal states; they'll auto-dismiss
        });
      }
    } catch { /* backend not up yet */ }
  }, []);

  useEffect(() => {
    pollActiveJob();
    const interval = setInterval(pollActiveJob, 5000);
    const onVis = () => { if (document.visibilityState === "visible") pollActiveJob(); };
    document.addEventListener("visibilitychange", onVis);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVis);
      if (dockStreamRef.current) { dockStreamRef.current(); dockStreamRef.current = null; }
      clearTimeout(dockDismissTimer.current);
    };
  }, [pollActiveJob]);

  const dockPause = async () => { if (dockJob) { try { await api.pauseJob(dockJob.id); pollActiveJob(); } catch {} } };
  const dockResume = async () => {
    if (dockJob) {
      try {
        await api.resumeJob(dockJob.id);
        // Re-subscribe
        if (dockStreamRef.current) { dockStreamRef.current(); dockStreamRef.current = null; }
        pollActiveJob();
      } catch {}
    }
  };
  const dockCancel = async () => { if (dockJob) { try { await api.cancelJob(dockJob.id); pollActiveJob(); } catch {} } };
  const dockRetry = async () => {
    if (dockJob) {
      try {
        await api.retryJob(dockJob.id);
        if (dockStreamRef.current) { dockStreamRef.current(); dockStreamRef.current = null; }
        pollActiveJob();
      } catch {}
    }
  };
  const dockNavigate = () => { setPage("oneclick"); setNavOpen(false); };

  // Poll until the whisper model is ready (or fails) — fast while it's
  // loading/downloading, then stops (no need to keep polling afterward).
  useEffect(() => {
    let alive = true;
    let timer;
    async function tick() {
      try {
        const s = await api.modelStatus();
        if (!alive) return;
        setModelStatus(s);
        if (s.status === "ready" || s.status === "error") return;
      } catch { /* server still coming up — keep trying */ }
      if (alive) timer = setTimeout(tick, 1000);
    }
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try { localStorage.setItem("cf-theme", theme); } catch { /* ignore */ }
  }, [theme]);

  useEffect(() => {
    let alive = true;
    const ping = () =>
      api.health()
        .then((d) => { if (alive) { setOnline(true); setDevice(d.device); } })
        .catch(() => { if (alive) setOnline(false); });
    ping();
    const t = setInterval(ping, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // The Create landing (step 1) is a clean, full-screen page: the sidebar + topbar
  // are HIDDEN (via the .is-landing class), not unmounted. <Create> stays mounted
  // across landing→editor so its source/url/upload state survives.
  const chromeless = page === "create" && step === 1;
  const t = TITLES[page];

  const go = (id) => { setPage(id); if (id === "create") setStep(1); setNavOpen(false); };

  if (modelStatus.status !== "ready") {
    return (
      <div className={"shell is-landing" + (navOpen ? " nav-open" : "")}>
        <ThemeSwitch theme={theme} setTheme={setTheme} fixed />
        <div className="content"><ModelSplash status={modelStatus} /></div>
      </div>
    );
  }

  return (
    <div className={"shell" + (chromeless ? " is-landing" : "") + (navOpen ? " nav-open" : "")}>
      {/* On the chromeless landing the topbar is hidden, so float the switcher. */}
      {chromeless && <ThemeSwitch theme={theme} setTheme={setTheme} fixed />}

      <div className="nav-scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />

      <aside className="sidebar">
        <div className="brand">
          <img src={logoImg} alt="Tech Hub" className="brand-logo-img" />
          <span className="brand-text">
            Tech Hub
            <span className="brand-by">Created by Barakah Tech</span>
          </span>
        </div>
        <nav className="nav">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={"nav-item" + (page === n.id ? " active" : "")}
              onClick={() => go(n.id)}
            >
              <n.icon /> {n.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div style={{ fontWeight: 700, color: "var(--text)", marginBottom: 2 }}>Tech Hub Studio</div>
          <div style={{ fontSize: "10.5px", color: "var(--accent)", marginBottom: 6 }}>Created by Barakah Tech</div>
          100% local AI pipeline<br />yt-dlp · faster-whisper · ffmpeg
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="nav-toggle" onClick={() => setNavOpen((o) => !o)} aria-label="Menu">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" />
            </svg>
          </button>
          <div className="topbar-titles">
            <h1>{t.h}</h1>
            <div className="sub">{t.sub}</div>
          </div>
          <div className="topbar-right">
            <ThemeSwitch theme={theme} setTheme={setTheme} />
            <span className={"badge " + (online ? "ok" : online === false ? "warn" : "")}>
              <span className="dot" />
              {online == null ? "Connecting…" : online ? `Backend · ${(device || "ready").toUpperCase()}` : "Backend offline"}
            </span>
          </div>
        </header>

        <div className="content">
          {/* Orbs are ALWAYS in the tree (hidden via CSS off the landing) so that
              <Create> never changes sibling-index. */}
          <div className="landing-orbs" aria-hidden="true">
            <span className="orb orb-1" />
            <span className="orb orb-2" />
            <span className="orb orb-3" />
            <span className="orb orb-4" />
            <span className="orb orb-5" />
          </div>
          {page === "oneclick" && <OneClickAI />}
          {page === "create" && <Create key="create" step={step} setStep={setStep} />}
          {page === "agent" && <AutoAgent />}
          {page === "queue" && <PublishingQueue />}
          {page === "channels" && <YouTubeDashboard />}
          {page === "library" && <Library />}
          {page === "settings" && <Settings />}
        </div>
      </div>

      {/* Persistent floating dock — visible on every tab when a job is active */}
      {dockJob && page !== "oneclick" && (
        <ActiveJobDock
          job={dockJob}
          onPause={dockPause}
          onResume={dockResume}
          onCancel={dockCancel}
          onRetry={dockRetry}
          onNavigate={dockNavigate}
        />
      )}
    </div>
  );
}
