import React, { useState, useEffect } from "react";
import { api } from "../api";

export default function AutoAgent() {
  const [channels, setChannels] = useState([]);
  const [watchedFiles, setWatchedFiles] = useState([]);
  const [selectedChannel, setSelectedChannel] = useState("");
  const [mode, setMode] = useState("manual_approval");
  const [clipsPerVideo, setClipsPerVideo] = useState(3);
  const [captionPreset, setCaptionPreset] = useState("hormozi_green");
  const [publishMode, setPublishMode] = useState("private");
  const [loading, setLoading] = useState(false);
  const [savedMsg, setSavedMsg] = useState("");
  const [scanMsg, setScanMsg] = useState("");

  const loadData = async () => {
    try {
      const [chList, watched] = await Promise.all([
        api.youtubeChannels().catch(() => []),
        api.watchedSources().catch(() => []),
      ]);
      setChannels(chList);
      setWatchedFiles(watched);
      if (chList.length > 0 && !selectedChannel) {
        setSelectedChannel(chList[0].id);
      }
    } catch (e) {
      console.error("Failed to load Auto Agent data:", e);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSaveConfig = async () => {
    setLoading(true);
    setSavedMsg("");
    try {
      await api.saveAgentConfig({
        channel_id: selectedChannel ? parseInt(selectedChannel, 10) : null,
        name: "Autonomous YouTube Agent",
        enabled: true,
        mode,
        clips_per_video: parseInt(clipsPerVideo, 10),
        min_duration: 15,
        max_duration: 60,
        caption_preset: captionPreset,
        publish_mode: publishMode,
      });
      setSavedMsg("Configuration saved successfully!");
    } catch (e) {
      setSavedMsg("Error saving configuration: " + e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleScanNow = async () => {
    setScanMsg("Scanning watched directory...");
    try {
      const res = await api.scanWatchedSources();
      setScanMsg(`Scan complete: ${res.new_or_matched_sources} new or updated master video(s).`);
      const updatedWatched = await api.watchedSources();
      setWatchedFiles(updatedWatched);
    } catch (e) {
      setScanMsg("Scan failed: " + e.message);
    }
  };

  return (
    <div style={{ padding: "2rem", maxWidth: "1000px", margin: "0 auto", color: "var(--text-main, #f8fafc)" }}>
      <div style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: "700", marginBottom: "0.5rem" }}>
          🤖 Mode B: Fully Autonomous YouTube Agent
        </h1>
        <p style={{ color: "var(--text-muted, #94a3b8)", fontSize: "0.95rem" }}>
          Continuously monitors your connected YouTube channel, matches long-form master videos in your local watched
          folder, extracts the best viral shorts, tracks speaker framing, and queues them for publishing.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: "2rem" }}>
        {/* Left: Configuration Rules */}
        <div style={{ background: "var(--bg-card, #1e293b)", padding: "1.5rem", borderRadius: "12px", border: "1px solid var(--border-color, #334155)" }}>
          <h2 style={{ fontSize: "1.2rem", fontWeight: "600", marginBottom: "1.25rem", color: "#f1f5f9" }}>
            Automation Settings
          </h2>

          <div style={{ marginBottom: "1.25rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.4rem", color: "#cbd5e1" }}>
              Monitored YouTube Channel
            </label>
            <select
              value={selectedChannel}
              onChange={(e) => setSelectedChannel(e.target.value)}
              style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff" }}
            >
              {channels.length === 0 ? (
                <option value="">No connected channels (Go to Channels tab)</option>
              ) : (
                channels.map((ch) => (
                  <option key={ch.id} value={ch.id}>
                    {ch.title} ({ch.youtube_channel_id})
                  </option>
                ))
              )}
            </select>
          </div>

          <div style={{ marginBottom: "1.25rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.4rem", color: "#cbd5e1" }}>
              Publishing Mode
            </label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff" }}
            >
              <option value="manual_approval">Manual Approval (Recommended - Review in Publishing Queue)</option>
              <option value="auto_publish">Auto-Publish (Autonomous Upload Directly to YouTube)</option>
            </select>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.25rem" }}>
            <div>
              <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.4rem", color: "#cbd5e1" }}>
                Clips Per Long Video
              </label>
              <select
                value={clipsPerVideo}
                onChange={(e) => setClipsPerVideo(e.target.value)}
                style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff" }}
              >
                <option value={1}>1 Best Clip</option>
                <option value={2}>2 Clips</option>
                <option value={3}>3 Clips (Standard)</option>
                <option value={5}>5 Clips</option>
              </select>
            </div>
            <div>
              <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.4rem", color: "#cbd5e1" }}>
                YouTube Privacy Status
              </label>
              <select
                value={publishMode}
                onChange={(e) => setPublishMode(e.target.value)}
                style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff" }}
              >
                <option value="private">Private (Default / Safe)</option>
                <option value="unlisted">Unlisted</option>
                <option value="public">Public (Direct)</option>
              </select>
            </div>
          </div>

          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.4rem", color: "#cbd5e1" }}>
              Caption Preset
            </label>
            <select
              value={captionPreset}
              onChange={(e) => setCaptionPreset(e.target.value)}
              style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff" }}
            >
              <option value="hormozi_green">Hormozi Green (Punchy / High-Contrast)</option>
              <option value="hormozi_yellow">Hormozi Yellow</option>
              <option value="beast_red">MrBeast Red Pop</option>
              <option value="karaoke_yellow">Karaoke Yellow (Word Highlight)</option>
              <option value="minimal">Minimal Clean</option>
            </select>
          </div>

          {savedMsg && (
            <div style={{ padding: "0.75rem", borderRadius: "6px", background: "#064e3b", color: "#a7f3d0", fontSize: "0.85rem", marginBottom: "1rem" }}>
              {savedMsg}
            </div>
          )}

          <button
            onClick={handleSaveConfig}
            disabled={loading}
            style={{
              width: "100%",
              padding: "0.75rem",
              borderRadius: "8px",
              background: "var(--accent, #84cc16)",
              color: "#0f172a",
              fontWeight: "700",
              border: "none",
              cursor: "pointer",
            }}
          >
            {loading ? "Saving..." : "Save Agent Configuration"}
          </button>
        </div>

        {/* Right: Watched Storage Ingestion */}
        <div style={{ background: "var(--bg-card, #1e293b)", padding: "1.5rem", borderRadius: "12px", border: "1px solid var(--border-color, #334155)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
            <h2 style={{ fontSize: "1.1rem", fontWeight: "600", color: "#f1f5f9" }}>📁 Watched Folder</h2>
            <button
              onClick={handleScanNow}
              style={{ padding: "0.4rem 0.8rem", borderRadius: "6px", background: "#334155", color: "#fff", border: "none", cursor: "pointer", fontSize: "0.8rem" }}
            >
              🔄 Scan Now
            </button>
          </div>

          <p style={{ fontSize: "0.85rem", color: "#94a3b8", marginBottom: "1rem" }}>
            Drop high-resolution original master videos into <code>watched/</code> folder. The agent matches them with new
            channel uploads to generate clips.
          </p>

          {scanMsg && (
            <div style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", background: "#1e1b4b", color: "#c7d2fe", fontSize: "0.8rem", marginBottom: "1rem" }}>
              {scanMsg}
            </div>
          )}

          <div style={{ maxHeight: "320px", overflowY: "auto" }}>
            {watchedFiles.length === 0 ? (
              <div style={{ padding: "2rem", textAlign: "center", color: "#64748b", fontSize: "0.85rem" }}>
                No video files detected in <code>watched/</code> directory.
              </div>
            ) : (
              watchedFiles.map((f, i) => (
                <div key={i} style={{ padding: "0.6rem 0.75rem", background: "#0f172a", borderRadius: "6px", marginBottom: "0.5rem", border: "1px solid #334155" }}>
                  <div style={{ fontSize: "0.85rem", fontWeight: "600", color: "#e2e8f0" }}>{f.filename}</div>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8", display: "flex", justifyContent: "space-between", marginTop: "0.2rem" }}>
                    <span>{(f.size_bytes / 1_048_576).toFixed(1)} MB</span>
                    <span>FP: {f.fingerprint.slice(0, 8)}...</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
