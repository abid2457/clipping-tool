import React, { useState, useEffect } from "react";
import { api } from "../api";

export default function YouTubeDashboard() {
  const [channels, setChannels] = useState([]);
  const [quota, setQuota] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  const loadData = async () => {
    setLoading(true);
    try {
      const [chs, q] = await Promise.all([
        api.youtubeChannels().catch(() => []),
        api.youtubeQuota().catch(() => null),
      ]);
      setChannels(chs);
      setQuota(q);
    } catch (e) {
      console.error("Failed to load channel data:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleConnectChannel = async () => {
    setAuthError("");
    try {
      const res = await api.getOAuthUrl();
      if (res.authorization_url) {
        window.open(res.authorization_url, "_blank");
      }
    } catch (e) {
      setAuthError(e.message || "Failed to generate authorization URL.");
    }
  };

  const consumed = quota?.consumed || 0;
  const limit = quota?.daily_limit || 10000;
  const pct = Math.min(100, Math.round((consumed / limit) * 100));
  const remainingUploads = Math.floor((quota?.remaining || 10000) / 1600);

  return (
    <div style={{ padding: "2rem", maxWidth: "900px", margin: "0 auto", color: "var(--text-main, #f8fafc)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "2rem" }}>
        <div>
          <h1 style={{ fontSize: "1.75rem", fontWeight: "700", marginBottom: "0.4rem" }}>
            📺 YouTube Channels & API Quota
          </h1>
          <p style={{ color: "var(--text-muted, #94a3b8)", fontSize: "0.95rem" }}>
            Manage authorized YouTube channels via Google OAuth 2.0 with machine-encrypted credential storage.
          </p>
        </div>
        <button
          onClick={handleConnectChannel}
          style={{
            padding: "0.75rem 1.25rem",
            borderRadius: "8px",
            background: "#ef4444",
            color: "#fff",
            fontWeight: "700",
            border: "none",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
          }}
        >
          <span>▶</span> Connect Channel
        </button>
      </div>

      {authError && (
        <div style={{ padding: "0.75rem 1rem", borderRadius: "8px", background: "rgba(239, 68, 68, 0.15)", border: "1px solid #ef4444", color: "#fca5a5", marginBottom: "1.5rem", fontSize: "0.9rem" }}>
          {authError}
        </div>
      )}

      {/* Quota Telemetry Card */}
      <div style={{ background: "var(--bg-card, #1e293b)", padding: "1.5rem", borderRadius: "12px", border: "1px solid var(--border-color, #334155)", marginBottom: "2rem" }}>
        <h2 style={{ fontSize: "1.1rem", fontWeight: "600", marginBottom: "1rem", color: "#f1f5f9" }}>
          📊 Daily API Quota Usage (YouTube Data API v3)
        </h2>

        <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", color: "#94a3b8", marginBottom: "0.5rem" }}>
          <span>{consumed.toLocaleString()} units consumed</span>
          <span>{quota?.remaining.toLocaleString() || "10,000"} units remaining</span>
        </div>

        <div style={{ width: "100%", height: "10px", background: "#0f172a", borderRadius: "5px", overflow: "hidden", marginBottom: "1rem" }}>
          <div style={{ width: `${pct}%`, height: "100%", background: pct > 80 ? "#ef4444" : "#00d29d", transition: "width 0.3s ease" }} />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: "1rem", textAlign: "center" }}>
          <div style={{ padding: "0.75rem", background: "#0f172a", borderRadius: "8px" }}>
            <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>Daily Limit</div>
            <div style={{ fontSize: "1.1rem", fontWeight: "700", color: "#f8fafc" }}>{limit.toLocaleString()}</div>
          </div>
          <div style={{ padding: "0.75rem", background: "#0f172a", borderRadius: "8px" }}>
            <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>Remaining Uploads Today</div>
            <div style={{ fontSize: "1.1rem", fontWeight: "700", color: "#00d29d" }}>~{remainingUploads}</div>
          </div>
          <div style={{ padding: "0.75rem", background: "#0f172a", borderRadius: "8px" }}>
            <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>Upload Cost</div>
            <div style={{ fontSize: "1.1rem", fontWeight: "700", color: "#f8fafc" }}>1,600 / vid</div>
          </div>
        </div>
      </div>

      {/* Connected Channels List */}
      <div>
        <h2 style={{ fontSize: "1.2rem", fontWeight: "600", marginBottom: "1rem", color: "#f1f5f9" }}>
          Connected Channels ({channels.length})
        </h2>

        {loading ? (
          <div style={{ padding: "2rem", textAlign: "center", color: "#94a3b8" }}>Loading channels...</div>
        ) : channels.length === 0 ? (
          <div style={{ padding: "3rem 2rem", textAlign: "center", background: "#1e293b", borderRadius: "12px", border: "1px solid #334155" }}>
            <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>🔌</div>
            <h3 style={{ fontSize: "1.1rem", fontWeight: "600", marginBottom: "0.4rem" }}>No Channels Connected Yet</h3>
            <p style={{ color: "#94a3b8", fontSize: "0.85rem", maxWidth: "450px", margin: "0 auto 1.25rem auto" }}>
              Click "Connect Channel" above to authorize your YouTube channel via Google OAuth 2.0 desktop authentication.
            </p>
          </div>
        ) : (
          <div style={{ display: "grid", gap: "1rem" }}>
            {channels.map((ch) => (
              <div
                key={ch.id}
                style={{
                  background: "#1e293b",
                  padding: "1.25rem",
                  borderRadius: "10px",
                  border: "1px solid #334155",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div>
                  <h3 style={{ fontSize: "1.05rem", fontWeight: "700", color: "#f8fafc", marginBottom: "0.2rem" }}>
                    {ch.title}
                  </h3>
                  <div style={{ fontSize: "0.8rem", color: "#94a3b8" }}>
                    Channel ID: <code>{ch.youtube_channel_id}</code>
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <span style={{ padding: "0.3rem 0.6rem", borderRadius: "4px", fontSize: "0.75rem", fontWeight: "700", background: "#064e3b", color: "#a7f3d0" }}>
                    {ch.status.toUpperCase()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
