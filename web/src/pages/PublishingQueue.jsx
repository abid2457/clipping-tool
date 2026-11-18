import React, { useState, useEffect } from "react";
import { api } from "../api";

export default function PublishingQueue() {
  const [queue, setQueue] = useState([]);
  const [loading, setLoading] = useState(true);
  const [channels, setChannels] = useState([]);
  const [actionMsg, setActionMsg] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  // Publish Modal State
  const [activeClip, setActiveClip] = useState(null);
  const [publishChannelId, setPublishChannelId] = useState("");
  const [publishTitle, setPublishTitle] = useState("");
  const [publishDesc, setPublishDesc] = useState("");
  const [publishTags, setPublishTags] = useState("");
  const [publishPrivacy, setPublishPrivacy] = useState("public");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(null);

  // V2: Upload Mode & AI Metadata State
  const [uploadMode, setUploadMode] = useState("shorts");
  const [aiTitles, setAiTitles] = useState([]);
  const [clipInfoData, setClipInfoData] = useState(null);
  const [isGeneratingMeta, setIsGeneratingMeta] = useState(false);
  const [isRegeneratingTitle, setIsRegeneratingTitle] = useState(false);
  const [isRegeneratingDesc, setIsRegeneratingDesc] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const [items, chs] = await Promise.all([
        api.publishingQueue().catch(() => []),
        api.youtubeChannels().catch(() => []),
      ]);
      setQueue(items);
      setChannels(chs);
      if (chs.length > 0 && !publishChannelId) {
        setPublishChannelId(chs[0].id);
      }
    } catch (e) {
      console.error("Failed to load queue:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openPublishModal = async (item) => {
    const meta = item.metadata || {};
    const defaultTitle = meta.primary_title || item.title || "Viral Short";
    const defaultDesc = meta.description || `Watch this highlight: ${defaultTitle}\n\n#Shorts #TechHub #BarakahTech`;
    const defaultTags = (meta.hashtags && meta.hashtags.length > 0)
      ? meta.hashtags.join(" ")
      : "#Shorts #Viral #TechHub #BarakahTech";

    setActiveClip(item);
    setPublishTitle(defaultTitle);
    setPublishDesc(defaultDesc);
    setPublishTags(defaultTags);
    setPublishPrivacy("public");
    setUploadSuccess(null);
    setErrorMsg("");
    setUploadMode("shorts");
    setAiTitles(meta.titles || []);
    setClipInfoData(null);

    // Fetch clip info in background
    try {
      const baseId = item.clip_id.includes("_") ? item.clip_id.split("_")[0] : item.clip_id;
      const idx = item.index !== undefined ? item.index : 0;
      const info = await api.clipInfo(baseId, idx);
      setClipInfoData(info);
      // Auto-select mode based on aspect ratio
      if (info && !info.is_vertical) {
        setUploadMode("video");
      }
    } catch (e) {
      console.warn("Could not fetch clip info:", e);
    }
  };

  const handleQuickConnect = async () => {
    try {
      const res = await api.getOAuthUrl();
      if (res.authorization_url) {
        window.open(res.authorization_url, "_blank");
      }
    } catch (e) {
      setErrorMsg(e.message || "Failed to start Google sign-in.");
    }
  };

  const handleGenerateAIMetadata = async () => {
    if (!activeClip) return;
    setIsGeneratingMeta(true);
    setErrorMsg("");
    try {
      const transcript = activeClip.metadata?.transcript || activeClip.title || "No transcript available";
      const duration = activeClip.duration || 30;
      const res = await api.generateMetadataV2(transcript, duration, uploadMode);

      if (res.titles && res.titles.length > 0) {
        setAiTitles(res.titles);
        setPublishTitle(res.primary_title || res.titles[0]);
      }
      if (res.description) setPublishDesc(res.description);
      if (res.hashtags) {
        setPublishTags(res.hashtags.join(" "));
      }
      if (res.tags) {
        const existingTags = publishTags.split(/[\s,]+/).filter(Boolean);
        const merged = [...new Set([...existingTags, ...res.tags.map(t => `#${t.replace(/^#/, "")}`)])];
        setPublishTags(merged.join(" "));
      }
      setActionMsg("✨ AI metadata generated for " + (uploadMode === "shorts" ? "YouTube Shorts" : "YouTube Video") + "!");
    } catch (e) {
      setErrorMsg("AI metadata generation failed: " + (e.message || "Unknown error"));
    } finally {
      setIsGeneratingMeta(false);
    }
  };

  const handleRegenerateTitles = async () => {
    if (!activeClip) return;
    setIsRegeneratingTitle(true);
    try {
      const transcript = activeClip.metadata?.transcript || activeClip.title || "";
      const res = await api.regenerateTitles(transcript, activeClip.duration || 30, uploadMode);
      if (res.titles && res.titles.length > 0) {
        setAiTitles(res.titles);
        setPublishTitle(res.titles[0]);
      }
    } catch (e) {
      setErrorMsg("Title regeneration failed: " + (e.message || ""));
    } finally {
      setIsRegeneratingTitle(false);
    }
  };

  const handleRegenerateDesc = async () => {
    if (!activeClip) return;
    setIsRegeneratingDesc(true);
    try {
      const transcript = activeClip.metadata?.transcript || activeClip.title || "";
      const res = await api.regenerateDesc(transcript, activeClip.duration || 30, uploadMode);
      if (res.description) {
        setPublishDesc(res.description);
      }
    } catch (e) {
      setErrorMsg("Description regeneration failed: " + (e.message || ""));
    } finally {
      setIsRegeneratingDesc(false);
    }
  };

  const handleExecutePublish = async () => {
    if (!publishChannelId) {
      setErrorMsg("Please select a connected YouTube channel.");
      return;
    }
    if (!publishTitle.trim()) {
      setErrorMsg("Video title cannot be empty.");
      return;
    }

    setIsUploading(true);
    setErrorMsg("");
    setUploadSuccess(null);

    try {
      const tagsArray = publishTags
        .split(/[\s,]+/)
        .map((t) => t.trim().replace(/^#/, ""))
        .filter(Boolean);

      const res = await api.uploadToYouTubeV2({
        clip_id: activeClip.clip_id,
        index: activeClip.index !== undefined ? activeClip.index : 0,
        channel_id: parseInt(publishChannelId, 10),
        title: publishTitle.trim(),
        description: publishDesc.trim(),
        tags: tagsArray,
        privacy_status: publishPrivacy,
        upload_mode: uploadMode,
      });

      setUploadSuccess({
        videoId: res.youtube_video_id,
        url: res.url || `https://youtu.be/${res.youtube_video_id}`,
        title: publishTitle,
        uploadMode: res.upload_mode || uploadMode,
      });

      setActionMsg(`✅ Successfully uploaded "${publishTitle}" as ${uploadMode === "shorts" ? "YouTube Short" : "YouTube Video"}!`);
      loadData();
    } catch (e) {
      setErrorMsg(e.message || "Failed to upload video to YouTube.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleQueueOnly = async (clipId) => {
    setActionMsg(`Queueing clip ${clipId}...`);
    try {
      await api.approveClip(clipId, publishChannelId ? parseInt(publishChannelId, 10) : null, "private");
      setActionMsg(`Clip ${clipId} marked as approved in queue.`);
      loadData();
    } catch (e) {
      setErrorMsg(`Failed: ${e.message}`);
    }
  };

  const handleReject = async (clipId) => {
    try {
      await api.rejectClip(clipId);
      setActionMsg(`Clip ${clipId} marked as rejected.`);
      loadData();
    } catch (e) {
      setErrorMsg(`Failed: ${e.message}`);
    }
  };

  // =========================================================================
  // Styles
  // =========================================================================
  const modeButtonStyle = (mode, active) => ({
    flex: 1,
    padding: "0.7rem 0.5rem",
    borderRadius: "8px",
    border: active ? "2px solid" : "1px solid #334155",
    borderColor: active ? (mode === "shorts" ? "#ef4444" : "#3b82f6") : "#334155",
    background: active ? (mode === "shorts" ? "rgba(239,68,68,0.15)" : "rgba(59,130,246,0.15)") : "#0f172a",
    color: active ? "#fff" : "#94a3b8",
    cursor: "pointer",
    textAlign: "center",
    fontWeight: active ? "700" : "500",
    fontSize: "0.85rem",
    transition: "all 0.2s",
  });

  const smallBtnStyle = (loading) => ({
    background: "transparent",
    border: "none",
    color: loading ? "#64748b" : "#38bdf8",
    cursor: loading ? "not-allowed" : "pointer",
    fontSize: "0.75rem",
    textDecoration: "underline",
    padding: "0",
  });

  const titlePillStyle = (selected) => ({
    padding: "0.35rem 0.65rem",
    borderRadius: "6px",
    background: selected ? "#00d29d" : "#334155",
    color: selected ? "#0f172a" : "#e2e8f0",
    border: "none",
    cursor: "pointer",
    fontSize: "0.78rem",
    fontWeight: selected ? "700" : "500",
    textAlign: "left",
    lineHeight: "1.3",
    transition: "all 0.15s",
  });

  // =========================================================================
  // Render
  // =========================================================================
  return (
    <div style={{ padding: "2rem", maxWidth: "1150px", margin: "0 auto", color: "var(--text-main, #f8fafc)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.5rem" }}>
        <div>
          <h1 style={{ fontSize: "1.75rem", fontWeight: "700", marginBottom: "0.4rem" }}>
            📋 Publishing Review Desk
          </h1>
          <p style={{ color: "var(--text-muted, #94a3b8)", fontSize: "0.95rem" }}>
            Review, customize titles, select YouTube channels, and publish short-form videos directly.
          </p>
        </div>
        <button
          onClick={loadData}
          style={{ padding: "0.5rem 1rem", borderRadius: "8px", background: "#334155", color: "#fff", border: "none", cursor: "pointer", fontWeight: "600" }}
        >
          🔄 Refresh
        </button>
      </div>

      {actionMsg && (
        <div style={{ padding: "0.75rem 1rem", borderRadius: "8px", background: "#064e3b", color: "#a7f3d0", marginBottom: "1.5rem", fontSize: "0.9rem" }}>
          {actionMsg}
        </div>
      )}

      {errorMsg && !activeClip && (
        <div style={{ padding: "0.75rem 1rem", borderRadius: "8px", background: "rgba(239, 68, 68, 0.2)", border: "1px solid #ef4444", color: "#fca5a5", marginBottom: "1.5rem", fontSize: "0.9rem" }}>
          {errorMsg}
        </div>
      )}

      {loading ? (
        <div style={{ padding: "3rem", textAlign: "center", color: "#94a3b8" }}>Loading queue items...</div>
      ) : queue.length === 0 ? (
        <div style={{ padding: "4rem 2rem", textAlign: "center", background: "#1e293b", borderRadius: "12px", border: "1px solid #334155" }}>
          <div style={{ fontSize: "2rem", marginBottom: "0.5rem" }}>🎉</div>
          <h2 style={{ fontSize: "1.2rem", fontWeight: "600", marginBottom: "0.5rem" }}>All Caught Up!</h2>
          <p style={{ color: "#94a3b8", fontSize: "0.9rem" }}>
            No clips pending review. Generate clips via One-Click AI or enable Auto Agent.
          </p>
        </div>
      ) : (
        <div style={{ display: "grid", gap: "1.5rem" }}>
          {queue.map((item) => {
            const meta = item.metadata || {};
            const titles = meta.titles || [item.title || "Untitled Clip"];
            const isPublished = item.publish_status === "published";

            return (
              <div
                key={item.clip_id}
                style={{
                  background: "#1e293b",
                  borderRadius: "12px",
                  border: "1px solid #334155",
                  padding: "1.5rem",
                  display: "grid",
                  gridTemplateColumns: "220px 1fr",
                  gap: "1.5rem",
                }}
              >
                {/* Left: Video Player */}
                <div>
                  <video
                    src={item.output_path}
                    controls
                    style={{ width: "100%", height: "300px", borderRadius: "8px", background: "#000", objectFit: "contain" }}
                  />
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.5rem", fontSize: "0.75rem", color: "#94a3b8" }}>
                    <span>Duration: {item.duration}s</span>
                    <span style={{ color: item.quality_status === "passed" ? "#00d29d" : "#f59e0b", fontWeight: "600" }}>
                      Quality: {item.quality_status.toUpperCase()}
                    </span>
                  </div>
                </div>

                {/* Right: Details & Action */}
                <div style={{ display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                  <div>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                      <div>
                        <span
                          style={{
                            padding: "0.2rem 0.6rem",
                            borderRadius: "4px",
                            fontSize: "0.75rem",
                            fontWeight: "700",
                            background: isPublished ? "#059669" : (item.review_status === "approved" ? "#0284c7" : item.review_status === "rejected" ? "#dc2626" : "#eab308"),
                            color: "#fff",
                            marginRight: "0.5rem",
                          }}
                        >
                          {isPublished ? "PUBLISHED TO YOUTUBE" : item.review_status.toUpperCase()}
                        </span>
                        <span style={{ fontSize: "0.85rem", color: "#00d29d", fontWeight: "700" }}>
                          ⭐ Virality Score: {item.score ? item.score.toFixed(1) : "8.0"} / 10
                        </span>
                      </div>
                      <span style={{ fontSize: "0.75rem", color: "#64748b" }}>{item.created_at?.slice(0, 16)}</span>
                    </div>

                    <h2 style={{ fontSize: "1.2rem", fontWeight: "700", marginBottom: "0.4rem", color: "#f8fafc" }}>
                      {item.title || "Clip " + (item.index + 1)}
                    </h2>

                    {meta.virality_reason && (
                      <p style={{ fontSize: "0.85rem", color: "#cbd5e1", fontStyle: "italic", marginBottom: "0.75rem" }}>
                        "{meta.virality_reason}"
                      </p>
                    )}

                    {titles.length > 1 && (
                      <div style={{ marginBottom: "0.75rem" }}>
                        <div style={{ fontSize: "0.8rem", fontWeight: "600", color: "#94a3b8", marginBottom: "0.3rem" }}>AI Title Options:</div>
                        <div style={{ display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                          {titles.map((t, idx) => (
                            <div key={idx} style={{ fontSize: "0.8rem", color: "#e2e8f0", padding: "0.3rem 0.5rem", background: "#0f172a", borderRadius: "4px" }}>
                              • {t}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {meta.hashtags && meta.hashtags.length > 0 && (
                      <div style={{ fontSize: "0.8rem", color: "#38bdf8", marginBottom: "1rem" }}>
                        {meta.hashtags.join(" ")}
                      </div>
                    )}
                  </div>

                  {/* Actions Footer */}
                  <div style={{ borderTop: "1px solid #334155", paddingTop: "1rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <a
                        href={item.output_path}
                        download={`clip_${item.clip_id}.mp4`}
                        style={{ padding: "0.5rem 0.75rem", borderRadius: "6px", background: "#334155", color: "#fff", textDecoration: "none", fontSize: "0.85rem", fontWeight: "600" }}
                      >
                        ⬇ Download MP4
                      </a>
                    </div>

                    <div style={{ display: "flex", gap: "0.6rem" }}>
                      {item.review_status !== "rejected" && !isPublished && (
                        <button
                          onClick={() => handleReject(item.clip_id)}
                          style={{ padding: "0.5rem 0.8rem", borderRadius: "6px", background: "rgba(239, 68, 68, 0.2)", border: "1px solid #ef4444", color: "#fca5a5", cursor: "pointer", fontSize: "0.85rem", fontWeight: "600" }}
                        >
                          Reject
                        </button>
                      )}
                      <button
                        onClick={() => openPublishModal(item)}
                        style={{
                          padding: "0.55rem 1.25rem",
                          borderRadius: "6px",
                          background: isPublished ? "#059669" : "var(--accent, #00d29d)",
                          color: "#0f172a",
                          border: "none",
                          cursor: "pointer",
                          fontSize: "0.9rem",
                          fontWeight: "700",
                          display: "flex",
                          alignItems: "center",
                          gap: "0.4rem",
                        }}
                      >
                        <span>▶</span> {isPublished ? "Publish Again" : "Approve & Publish to YouTube"}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ========================================================================= */}
      {/* Interactive Publish Modal with Upload Mode & AI Metadata */}
      {/* ========================================================================= */}
      {activeClip && (
        <div
          style={{
            position: "fixed",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: "rgba(0, 0, 0, 0.8)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 1000,
            backdropFilter: "blur(4px)",
          }}
        >
          <div
            style={{
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: "16px",
              padding: "2rem",
              width: "90%",
              maxWidth: "640px",
              maxHeight: "90vh",
              overflowY: "auto",
              boxShadow: "0 20px 40px rgba(0,0,0,0.6)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
              <h2 style={{ fontSize: "1.3rem", fontWeight: "700", color: "#f8fafc", margin: 0 }}>
                🚀 Publish to YouTube
              </h2>
              <button
                onClick={() => setActiveClip(null)}
                style={{ background: "transparent", border: "none", color: "#94a3b8", fontSize: "1.5rem", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>

            {errorMsg && (
              <div style={{ padding: "0.75rem", borderRadius: "8px", background: "rgba(239,68,68,0.2)", border: "1px solid #ef4444", color: "#fca5a5", fontSize: "0.85rem", marginBottom: "1rem" }}>
                {errorMsg}
              </div>
            )}

            {uploadSuccess ? (
              <div style={{ textAlign: "center", padding: "1.5rem 0" }}>
                <div style={{ fontSize: "3rem", marginBottom: "0.5rem" }}>🎉</div>
                <h3 style={{ fontSize: "1.25rem", fontWeight: "700", color: "#00d29d", marginBottom: "0.5rem" }}>
                  {uploadSuccess.uploadMode === "shorts" ? "Short" : "Video"} Published Successfully!
                </h3>
                <p style={{ color: "#cbd5e1", fontSize: "0.95rem", marginBottom: "0.5rem" }}>
                  "{uploadSuccess.title}" is now uploaded to your channel.
                </p>
                <p style={{ color: "#94a3b8", fontSize: "0.8rem", marginBottom: "1.5rem" }}>
                  {uploadSuccess.uploadMode === "shorts"
                    ? "🎬 Uploaded as YouTube Short (vertical 9:16)"
                    : "📺 Uploaded as regular YouTube Video"}
                </p>
                <div style={{ display: "flex", gap: "1rem", justifyContent: "center" }}>
                  <a
                    href={uploadSuccess.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{
                      padding: "0.75rem 1.5rem",
                      borderRadius: "8px",
                      background: "#ef4444",
                      color: "#fff",
                      textDecoration: "none",
                      fontWeight: "700",
                      fontSize: "0.95rem",
                    }}
                  >
                    Watch on YouTube ↗
                  </a>
                  <button
                    onClick={() => setActiveClip(null)}
                    style={{
                      padding: "0.75rem 1.5rem",
                      borderRadius: "8px",
                      background: "#334155",
                      color: "#fff",
                      border: "none",
                      fontWeight: "600",
                      cursor: "pointer",
                    }}
                  >
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <div>
                {/* ============ UPLOAD MODE SELECTOR ============ */}
                <div style={{ marginBottom: "1.25rem" }}>
                  <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1", marginBottom: "0.5rem" }}>
                    Upload Mode
                  </label>
                  <div style={{ display: "flex", gap: "0.75rem" }}>
                    <button
                      type="button"
                      onClick={() => setUploadMode("shorts")}
                      style={modeButtonStyle("shorts", uploadMode === "shorts")}
                    >
                      <div style={{ fontSize: "1.3rem", marginBottom: "0.2rem" }}>🎬</div>
                      <div style={{ fontWeight: "700" }}>YouTube Shorts</div>
                      <div style={{ fontSize: "0.72rem", color: uploadMode === "shorts" ? "#fca5a5" : "#64748b", marginTop: "0.15rem" }}>
                        9:16 vertical · ≤ 3 min
                      </div>
                    </button>
                    <button
                      type="button"
                      onClick={() => setUploadMode("video")}
                      style={modeButtonStyle("video", uploadMode === "video")}
                    >
                      <div style={{ fontSize: "1.3rem", marginBottom: "0.2rem" }}>📺</div>
                      <div style={{ fontWeight: "700" }}>YouTube Video</div>
                      <div style={{ fontSize: "0.72rem", color: uploadMode === "video" ? "#93c5fd" : "#64748b", marginTop: "0.15rem" }}>
                        16:9 landscape · any length
                      </div>
                    </button>
                  </div>
                </div>

                {/* ============ CLIP INFO BADGE ============ */}
                {clipInfoData && (
                  <div style={{ marginBottom: "1.25rem" }}>
                    <div style={{
                      display: "flex", flexWrap: "wrap", gap: "0.5rem",
                      padding: "0.6rem 0.85rem", borderRadius: "8px",
                      background: "rgba(15, 23, 42, 0.8)", border: "1px solid #334155",
                    }}>
                      <span style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
                        📐 {clipInfoData.width}×{clipInfoData.height}
                      </span>
                      <span style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
                        ⏱ {clipInfoData.duration}s
                      </span>
                      <span style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
                        📏 {clipInfoData.aspect_ratio}
                      </span>
                      <span style={{
                        fontSize: "0.78rem", fontWeight: "600",
                        color: clipInfoData.is_shorts_eligible ? "#00d29d" : "#f59e0b",
                      }}>
                        {clipInfoData.is_shorts_eligible ? "✅ Shorts Eligible (9:16)" : "ℹ️ 16:9 Horizontal"}
                      </span>
                    </div>
                    {uploadMode === "shorts" && !clipInfoData.is_shorts_eligible && (
                      <div style={{
                        marginTop: "0.4rem",
                        padding: "0.4rem 0.75rem",
                        borderRadius: "6px",
                        background: "rgba(59, 130, 246, 0.1)",
                        border: "1px solid rgba(59, 130, 246, 0.3)",
                        fontSize: "0.75rem",
                        color: "#93c5fd",
                      }}>
                        ✨ <strong>Auto-Format Active:</strong> This 16:9 horizontal clip will be automatically transcoded to a 1080×1920 vertical 9:16 Short with blurred background before uploading to YouTube!
                      </div>
                    )}
                  </div>
                )}

                {/* ============ AI METADATA GENERATOR BUTTON ============ */}
                <div style={{ marginBottom: "1.25rem" }}>
                  <button
                    type="button"
                    onClick={handleGenerateAIMetadata}
                    disabled={isGeneratingMeta}
                    style={{
                      width: "100%",
                      padding: "0.7rem",
                      borderRadius: "8px",
                      background: isGeneratingMeta ? "#475569" : "linear-gradient(135deg, #6366f1, #8b5cf6)",
                      color: "#fff",
                      border: "none",
                      cursor: isGeneratingMeta ? "not-allowed" : "pointer",
                      fontWeight: "700",
                      fontSize: "0.9rem",
                    }}
                  >
                    {isGeneratingMeta
                      ? "✨ Generating AI Metadata..."
                      : `✨ Generate AI Metadata (${uploadMode === "shorts" ? "Shorts" : "Video"} Mode)`}
                  </button>
                </div>

                {/* ============ CHANNEL SELECTOR ============ */}
                <div style={{ marginBottom: "1.25rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.4rem" }}>
                    <label style={{ fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1" }}>
                      Target YouTube Channel
                    </label>
                    <button
                      type="button"
                      onClick={loadData}
                      style={{ background: "transparent", border: "none", color: "#38bdf8", cursor: "pointer", fontSize: "0.75rem", textDecoration: "underline" }}
                    >
                      🔄 Refresh
                    </button>
                  </div>
                  {channels.length === 0 ? (
                    <div style={{ padding: "0.85rem 1rem", borderRadius: "8px", background: "rgba(239, 68, 68, 0.1)", border: "1px solid rgba(239, 68, 68, 0.3)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                      <span style={{ fontSize: "0.85rem", color: "#fca5a5" }}>⚠️ No YouTube channel linked yet</span>
                      <button
                        type="button"
                        onClick={handleQuickConnect}
                        style={{ padding: "0.4rem 0.85rem", borderRadius: "6px", background: "#ef4444", color: "#fff", border: "none", cursor: "pointer", fontSize: "0.8rem", fontWeight: "700" }}
                      >
                        ▶ Connect with Google
                      </button>
                    </div>
                  ) : (
                    <select
                      value={publishChannelId}
                      onChange={(e) => setPublishChannelId(e.target.value)}
                      disabled={isUploading}
                      style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.9rem" }}
                    >
                      {channels.map((ch) => (
                        <option key={ch.id} value={ch.id}>
                          {ch.title} ({ch.youtube_channel_id})
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                {/* ============ TITLE WITH REGENERATE ============ */}
                <div style={{ marginBottom: "1.25rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.4rem" }}>
                    <label style={{ fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1" }}>Video Title</label>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                      <button
                        type="button"
                        onClick={handleRegenerateTitles}
                        disabled={isRegeneratingTitle}
                        style={smallBtnStyle(isRegeneratingTitle)}
                      >
                        {isRegeneratingTitle ? "⏳ Regenerating..." : "🔄 Regenerate Titles"}
                      </button>
                      <span style={{ fontSize: "0.75rem", color: publishTitle.length > (uploadMode === "shorts" ? 55 : 90) ? "#f87171" : "#94a3b8" }}>
                        {publishTitle.length} / {uploadMode === "shorts" ? 60 : 100}
                      </span>
                    </div>
                  </div>
                  <input
                    type="text"
                    value={publishTitle}
                    onChange={(e) => setPublishTitle(e.target.value)}
                    maxLength={uploadMode === "shorts" ? 60 : 100}
                    disabled={isUploading}
                    style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.9rem", boxSizing: "border-box" }}
                  />

                  {/* AI Title Pills */}
                  {aiTitles.length > 0 && (
                    <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.35rem" }}>
                      <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>AI Title Suggestions (click to use):</span>
                      {aiTitles.map((opt, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => setPublishTitle(opt)}
                          style={titlePillStyle(publishTitle === opt)}
                        >
                          {i + 1}. {opt}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* ============ DESCRIPTION WITH REGENERATE ============ */}
                <div style={{ marginBottom: "1.25rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.4rem" }}>
                    <label style={{ fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1" }}>Description</label>
                    <button
                      type="button"
                      onClick={handleRegenerateDesc}
                      disabled={isRegeneratingDesc}
                      style={smallBtnStyle(isRegeneratingDesc)}
                    >
                      {isRegeneratingDesc ? "⏳ Regenerating..." : "🔄 Regenerate Description"}
                    </button>
                  </div>
                  <textarea
                    rows={4}
                    value={publishDesc}
                    onChange={(e) => setPublishDesc(e.target.value)}
                    disabled={isUploading}
                    style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.85rem", resize: "vertical", boxSizing: "border-box" }}
                  />
                </div>

                {/* ============ TAGS & PRIVACY ============ */}
                <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: "1rem", marginBottom: "1.5rem" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1", marginBottom: "0.4rem" }}>
                      Hashtags / Tags
                    </label>
                    <input
                      type="text"
                      value={publishTags}
                      onChange={(e) => setPublishTags(e.target.value)}
                      disabled={isUploading}
                      style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.85rem", boxSizing: "border-box" }}
                    />
                  </div>
                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1", marginBottom: "0.4rem" }}>
                      Visibility
                    </label>
                    <select
                      value={publishPrivacy}
                      onChange={(e) => setPublishPrivacy(e.target.value)}
                      disabled={isUploading}
                      style={{ width: "100%", padding: "0.7rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.85rem" }}
                    >
                      <option value="public">Public</option>
                      <option value="unlisted">Unlisted</option>
                      <option value="private">Private</option>
                    </select>
                  </div>
                </div>

                {/* ============ ACTION BUTTONS ============ */}
                <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    onClick={() => setActiveClip(null)}
                    disabled={isUploading}
                    style={{ padding: "0.75rem 1.25rem", borderRadius: "8px", background: "#334155", color: "#fff", border: "none", cursor: "pointer", fontWeight: "600" }}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleExecutePublish}
                    disabled={isUploading || channels.length === 0}
                    style={{
                      padding: "0.75rem 1.5rem",
                      borderRadius: "8px",
                      background: isUploading ? "#475569" : (uploadMode === "shorts" ? "#ef4444" : "#3b82f6"),
                      color: "#fff",
                      border: "none",
                      cursor: (isUploading || channels.length === 0) ? "not-allowed" : "pointer",
                      fontWeight: "700",
                      fontSize: "0.95rem",
                    }}
                  >
                    {isUploading
                      ? "Uploading to YouTube..."
                      : uploadMode === "shorts"
                        ? "🎬 Upload as Short"
                        : "📺 Upload as Video"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
