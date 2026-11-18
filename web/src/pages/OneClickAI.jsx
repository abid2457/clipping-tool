import React, { useState, useEffect, useRef } from "react";
import { api, streamProgress } from "../api";

export default function OneClickAI() {
  const [sourceType, setSourceType] = useState("url"); // "url" | "system"
  const [url, setUrl] = useState("");
  const [uploadedFile, setUploadedFile] = useState(null);
  const [uploadPct, setUploadPct] = useState(null);
  const [isUploadingFile, setIsUploadingFile] = useState(false);
  const fileInputRef = useRef(null);

  // Upload & Generation Mode
  const [uploadMode, setUploadMode] = useState("shorts"); // "shorts" | "video"
  const [numClips, setNumClips] = useState(3);
  const [durationPref, setDurationPref] = useState(30);

  // Job progress
  const [isGenerating, setIsGenerating] = useState(false);
  const [progressMsg, setProgressMsg] = useState("");
  const [pct, setPct] = useState(0);
  const [results, setResults] = useState([]);
  const [lastJobId, setLastJobId] = useState("");
  const [error, setError] = useState(null);

  // Publish Modal State (for direct publishing from OneClickAI)
  const [publishModalClip, setPublishModalClip] = useState(null);
  const [channels, setChannels] = useState([]);
  const [publishChannelId, setPublishChannelId] = useState("");
  const [publishTitle, setPublishTitle] = useState("");
  const [publishDesc, setPublishDesc] = useState("");
  const [publishTags, setPublishTags] = useState("");
  const [publishPrivacy, setPublishPrivacy] = useState("public");
  const [modalUploadMode, setModalUploadMode] = useState("shorts");
  const [aiTitles, setAiTitles] = useState([]);
  const [isUploadingToYT, setIsUploadingToYT] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [modalError, setModalError] = useState("");
  const [isGeneratingMeta, setIsGeneratingMeta] = useState(false);

  useEffect(() => {
    api.youtubeChannels().then((chs) => {
      setChannels(chs || []);
      if (chs && chs.length > 0) setPublishChannelId(chs[0].id);
    }).catch(() => {});
  }, []);

  const handleFileUpload = async (file) => {
    if (!file) return;
    setIsUploadingFile(true);
    setUploadPct(0);
    setError(null);
    try {
      const res = await api.upload(file, (p) => setUploadPct(p));
      setUploadedFile({ upload_id: res.upload_id, filename: res.filename || file.name, size: file.size });
    } catch (e) {
      setError(e.message || "File upload failed.");
      setUploadedFile(null);
    } finally {
      setIsUploadingFile(false);
    }
  };

  const handleGenerate = async () => {
    if (sourceType === "url" && !url.trim()) {
      setError("Please paste a valid video URL.");
      return;
    }
    if (sourceType === "system" && !uploadedFile) {
      setError("Please select and upload a video file from your system.");
      return;
    }

    setError(null);
    setIsGenerating(true);
    setProgressMsg("Initializing AI Clipping Engine...");
    setPct(5);
    setResults([]);

    const payload = {
      num_clips: parseInt(numClips, 10),
      clip_length: parseFloat(durationPref),
      aspect_ratio: uploadMode === "shorts" ? "9:16" : "16:9",
      fit_mode: uploadMode === "shorts" ? "crop" : "fit",
      caption_style: "hormozi_green",
      use_ai: true,
    };

    if (sourceType === "url") {
      payload.video_url = url.trim();
    } else {
      payload.upload_id = uploadedFile.upload_id;
      payload.upload_name = uploadedFile.filename;
    }

    try {
      const resp = await api.generate(payload);
      const jobId = resp.job_id;
      setLastJobId(jobId);

      const unsub = streamProgress(
        jobId,
        (snap) => {
          if (snap.message) setProgressMsg(snap.message);
          if (snap.progress !== undefined) setPct(Math.round(snap.progress * 100));
          if (snap.clips && snap.clips.length > 0) setResults(snap.clips);
          if (snap.status === "done") {
            setIsGenerating(false);
            unsub();
          } else if (snap.status === "error") {
            setError(snap.error || "Generation encountered an error.");
            setIsGenerating(false);
            unsub();
          }
        },
        () => {
          setIsGenerating(false);
        }
      );
    } catch (e) {
      setError(e.message || "Failed to start generation.");
      setIsGenerating(false);
    }
  };

  const openPublishModal = async (clip, idx) => {
    const defaultTitle = clip.title || `Clip ${idx + 1}`;
    setPublishModalClip({ ...clip, index: idx });
    setPublishTitle(defaultTitle);
    setPublishDesc(`Watch this highlight: ${defaultTitle}\n\n#Shorts #TechHub #BarakahTech`);
    setPublishTags("#Shorts #Viral #TechHub #BarakahTech");
    setPublishPrivacy("public");
    setModalUploadMode(uploadMode);
    setUploadSuccess(null);
    setModalError("");
    setAiTitles([]);

    // Automatically trigger AI metadata generation
    setIsGeneratingMeta(true);
    try {
      const res = await api.generateMetadataV2(clip.title || "", clip.end - clip.start, uploadMode);
      if (res.titles && res.titles.length > 0) {
        setAiTitles(res.titles);
        setPublishTitle(res.primary_title || res.titles[0]);
      }
      if (res.description) setPublishDesc(res.description);
      if (res.hashtags) setPublishTags(res.hashtags.join(" "));
    } catch (e) {
      console.warn("AI metadata generation fallback:", e);
    } finally {
      setIsGeneratingMeta(false);
    }
  };

  const handleExecuteUpload = async () => {
    if (!publishChannelId) {
      setModalError("Please select a connected YouTube channel.");
      return;
    }
    if (!publishTitle.trim()) {
      setModalError("Title cannot be empty.");
      return;
    }

    setIsUploadingToYT(true);
    setModalError("");

    try {
      const tagsArray = publishTags.split(/[\s,]+/).map((t) => t.trim().replace(/^#/, "")).filter(Boolean);
      const cleanClipId = lastJobId || (publishModalClip.url ? publishModalClip.url.split("/")[2] : "job");

      const res = await api.uploadToYouTubeV2({
        clip_id: cleanClipId,
        index: publishModalClip.index,
        channel_id: parseInt(publishChannelId, 10),
        title: publishTitle.trim(),
        description: publishDesc.trim(),
        tags: tagsArray,
        privacy_status: publishPrivacy,
        upload_mode: modalUploadMode,
      });

      setUploadSuccess({
        videoId: res.youtube_video_id,
        url: res.url || `https://youtu.be/${res.youtube_video_id}`,
        title: publishTitle,
      });
    } catch (e) {
      setModalError(e.message || "Upload failed.");
    } finally {
      setIsUploadingToYT(false);
    }
  };

  return (
    <div style={{ padding: "2rem", maxWidth: "1050px", margin: "0 auto", color: "var(--text-main, #f8fafc)" }}>
      <div style={{ marginBottom: "2rem" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: "700", marginBottom: "0.5rem" }}>
          ⚡ One-Click AI Clipping & YouTube Upload
        </h1>
        <p style={{ color: "var(--text-muted, #94a3b8)", fontSize: "0.95rem" }}>
          Select video source, choose between <strong>YouTube Shorts</strong> or <strong>YouTube Video</strong>, and let local AI generate viral clips and SEO metadata automatically.
        </p>
      </div>

      <div style={{ background: "var(--bg-card, #1e293b)", padding: "1.75rem", borderRadius: "12px", border: "1px solid var(--border-color, #334155)", marginBottom: "2rem" }}>
        {/* Source Selector: URL vs System */}
        <div style={{ marginBottom: "1.5rem" }}>
          <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.5rem", color: "#cbd5e1" }}>
            1. Select Video Source
          </label>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <button
              type="button"
              onClick={() => setSourceType("url")}
              style={{
                flex: 1,
                padding: "0.75rem",
                borderRadius: "8px",
                border: sourceType === "url" ? "2px solid #00d29d" : "1px solid #334155",
                background: sourceType === "url" ? "rgba(0, 210, 157, 0.15)" : "#0f172a",
                color: sourceType === "url" ? "#fff" : "#94a3b8",
                fontWeight: "700",
                cursor: "pointer",
              }}
            >
              🔗 Web Video URL
            </button>
            <button
              type="button"
              onClick={() => setSourceType("system")}
              style={{
                flex: 1,
                padding: "0.75rem",
                borderRadius: "8px",
                border: sourceType === "system" ? "2px solid #00d29d" : "1px solid #334155",
                background: sourceType === "system" ? "rgba(0, 210, 157, 0.15)" : "#0f172a",
                color: sourceType === "system" ? "#fff" : "#94a3b8",
                fontWeight: "700",
                cursor: "pointer",
              }}
            >
              💻 System Upload (Local File)
            </button>
          </div>
        </div>

        {/* Source Input details */}
        {sourceType === "url" ? (
          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.4rem", color: "#94a3b8" }}>
              Video URL (YouTube or Web Video)
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              disabled={isGenerating}
              style={{
                width: "100%",
                padding: "0.75rem 1rem",
                borderRadius: "8px",
                background: "#0f172a",
                border: "1px solid #334155",
                color: "#fff",
                fontSize: "0.95rem",
                boxSizing: "border-box",
              }}
            />
          </div>
        ) : (
          <div style={{ marginBottom: "1.5rem" }}>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.4rem", color: "#94a3b8" }}>
              Upload Video File from System
            </label>
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*"
              style={{ display: "none" }}
              onChange={(e) => handleFileUpload(e.target.files[0])}
            />
            <div
              onClick={() => fileInputRef.current?.click()}
              style={{
                border: "2px dashed #475569",
                borderRadius: "8px",
                padding: "1.5rem",
                textAlign: "center",
                background: "#0f172a",
                cursor: "pointer",
                transition: "border 0.2s",
              }}
            >
              {isUploadingFile ? (
                <div>
                  <div style={{ fontSize: "1rem", color: "#00d29d", marginBottom: "0.5rem" }}>
                    Uploading to Local System: {uploadPct}%
                  </div>
                  <div style={{ width: "200px", height: "6px", background: "#334155", borderRadius: "3px", margin: "0 auto", overflow: "hidden" }}>
                    <div style={{ width: `${uploadPct}%`, height: "100%", background: "#00d29d" }} />
                  </div>
                </div>
              ) : uploadedFile ? (
                <div>
                  <span style={{ color: "#00d29d", fontWeight: "700" }}>✓ {uploadedFile.filename}</span>
                  <span style={{ color: "#94a3b8", fontSize: "0.8rem", marginLeft: "0.5rem" }}>
                    ({(uploadedFile.size / 1024 / 1024).toFixed(1)} MB) — Click to change
                  </span>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: "1.75rem", marginBottom: "0.3rem" }}>📁</div>
                  <div style={{ color: "#e2e8f0", fontWeight: "600", fontSize: "0.95rem" }}>
                    Click or Drag video file here to upload
                  </div>
                  <div style={{ color: "#64748b", fontSize: "0.8rem", marginTop: "0.2rem" }}>
                    Supports MP4, MKV, MOV, WEBM (No cloud upload, processed 100% locally)
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* FEATURE 1: Upload Mode Selector */}
        <div style={{ marginBottom: "1.5rem" }}>
          <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.5rem", color: "#cbd5e1" }}>
            2. Choose YouTube Upload Mode
          </label>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
            <div
              onClick={() => {
                setUploadMode("shorts");
                setDurationPref(30);
              }}
              style={{
                padding: "1rem",
                borderRadius: "10px",
                border: uploadMode === "shorts" ? "2px solid #ef4444" : "1px solid #334155",
                background: uploadMode === "shorts" ? "rgba(239, 68, 68, 0.12)" : "#0f172a",
                cursor: "pointer",
                transition: "all 0.2s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.3rem" }}>
                <span style={{ fontSize: "1.4rem" }}>🎬</span>
                <span style={{ fontWeight: "700", color: "#fff", fontSize: "1rem" }}>YouTube Shorts</span>
                {uploadMode === "shorts" && <span style={{ marginLeft: "auto", color: "#ef4444", fontWeight: "700" }}>✓ Selected</span>}
              </div>
              <p style={{ margin: 0, fontSize: "0.8rem", color: "#94a3b8", lineHeight: "1.4" }}>
                Vertical 9:16 aspect ratio (1080×1920). AI face tracking & hook detection. ≤ 60s length.
              </p>
            </div>

            <div
              onClick={() => {
                setUploadMode("video");
                setDurationPref(60);
              }}
              style={{
                padding: "1rem",
                borderRadius: "10px",
                border: uploadMode === "video" ? "2px solid #3b82f6" : "1px solid #334155",
                background: uploadMode === "video" ? "rgba(59, 130, 246, 0.12)" : "#0f172a",
                cursor: "pointer",
                transition: "all 0.2s",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "0.3rem" }}>
                <span style={{ fontSize: "1.4rem" }}>📺</span>
                <span style={{ fontWeight: "700", color: "#fff", fontSize: "1rem" }}>YouTube Video</span>
                {uploadMode === "video" && <span style={{ marginLeft: "auto", color: "#3b82f6", fontWeight: "700" }}>✓ Selected</span>}
              </div>
              <p style={{ margin: 0, fontSize: "0.8rem", color: "#94a3b8", lineHeight: "1.4" }}>
                Landscape 16:9 aspect ratio (1920×1080). Preserves original framing. SEO search metadata.
              </p>
            </div>
          </div>
        </div>

        {/* Clip Counts and Duration */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem", marginBottom: "1.5rem" }}>
          <div>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.5rem", color: "#cbd5e1" }}>
              Number of Clips
            </label>
            <select
              value={numClips}
              onChange={(e) => setNumClips(e.target.value)}
              disabled={isGenerating}
              style={{ width: "100%", padding: "0.75rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff" }}
            >
              <option value={1}>1 Best Highlight</option>
              <option value={3}>3 Clips (Recommended)</option>
              <option value={5}>5 Clips</option>
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", marginBottom: "0.5rem", color: "#cbd5e1" }}>
              Target Duration
            </label>
            <select
              value={durationPref}
              onChange={(e) => setDurationPref(e.target.value)}
              disabled={isGenerating}
              style={{ width: "100%", padding: "0.75rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff" }}
            >
              {uploadMode === "shorts" ? (
                <>
                  <option value={30}>30s Short (Fast Retention)</option>
                  <option value={45}>45s Standard Short</option>
                  <option value={60}>60s Max Shorts Length</option>
                </>
              ) : (
                <>
                  <option value={60}>60s Video Highlight</option>
                  <option value={90}>90s In-Depth Segment</option>
                  <option value={120}>2 Minutes Detailed Breakdown</option>
                </>
              )}
            </select>
          </div>
        </div>

        {error && (
          <div style={{ padding: "0.75rem 1rem", background: "rgba(239, 68, 68, 0.15)", border: "1px solid #ef4444", borderRadius: "8px", color: "#fca5a5", marginBottom: "1rem", fontSize: "0.9rem" }}>
            {error}
          </div>
        )}

        <button
          onClick={handleGenerate}
          disabled={isGenerating || isUploadingFile}
          style={{
            width: "100%",
            padding: "0.9rem",
            borderRadius: "8px",
            background: isGenerating ? "#475569" : "var(--accent, #00d29d)",
            color: isGenerating ? "#94a3b8" : "#0f172a",
            fontWeight: "700",
            fontSize: "1rem",
            cursor: (isGenerating || isUploadingFile) ? "not-allowed" : "pointer",
            border: "none",
            transition: "all 0.2s",
          }}
        >
          {isGenerating
            ? `Processing ${uploadMode === "shorts" ? "Shorts" : "Videos"}... ${pct}%`
            : `🚀 Generate AI ${uploadMode === "shorts" ? "YouTube Shorts" : "YouTube Videos"}`}
        </button>

        {isGenerating && (
          <div style={{ marginTop: "1.25rem" }}>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", marginBottom: "0.4rem", color: "#94a3b8" }}>
              <span>{progressMsg}</span>
              <span>{pct}%</span>
            </div>
            <div style={{ width: "100%", height: "8px", background: "#0f172a", borderRadius: "4px", overflow: "hidden" }}>
              <div style={{ width: `${pct}%`, height: "100%", background: "#00d29d", transition: "width 0.3s ease" }} />
            </div>
          </div>
        )}
      </div>

      {/* Results grid */}
      {results.length > 0 && (
        <div>
          <h2 style={{ fontSize: "1.3rem", fontWeight: "700", marginBottom: "1rem" }}>
            ✨ Ready {uploadMode === "shorts" ? "Shorts" : "Videos"} ({results.length})
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "1.5rem" }}>
            {results.map((clip, idx) => (
              <div key={idx} style={{ background: "#1e293b", borderRadius: "10px", padding: "1rem", border: "1px solid #334155", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
                <div>
                  <video
                    src={clip.url}
                    controls
                    style={{ width: "100%", maxHeight: "320px", borderRadius: "6px", background: "#000", marginBottom: "0.75rem", objectFit: "contain" }}
                  />
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "#94a3b8", marginBottom: "0.3rem" }}>
                    <span>{uploadMode === "shorts" ? "🎬 Shorts (9:16)" : "📺 Video (16:9)"}</span>
                    <span>Duration: {(clip.end - clip.start).toFixed(1)}s</span>
                  </div>
                  <h3 style={{ fontSize: "0.95rem", fontWeight: "600", marginBottom: "0.75rem", color: "#f8fafc" }}>
                    {clip.title}
                  </h3>
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                  <button
                    onClick={() => openPublishModal(clip, idx)}
                    style={{
                      width: "100%",
                      padding: "0.6rem",
                      borderRadius: "6px",
                      background: uploadMode === "shorts" ? "#ef4444" : "#3b82f6",
                      color: "#fff",
                      border: "none",
                      cursor: "pointer",
                      fontWeight: "700",
                      fontSize: "0.85rem",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: "0.4rem",
                    }}
                  >
                    <span>▶</span> Publish to YouTube
                  </button>

                  <div style={{ display: "flex", gap: "0.5rem" }}>
                    <a
                      href={clip.url}
                      download={clip.filename || `clip_${idx + 1}.mp4`}
                      style={{
                        flex: 1,
                        textAlign: "center",
                        padding: "0.45rem",
                        borderRadius: "6px",
                        background: "#334155",
                        color: "#fff",
                        textDecoration: "none",
                        fontSize: "0.8rem",
                        fontWeight: "600",
                      }}
                    >
                      ⬇ Download
                    </a>
                    <a
                      href={api.subtitleUrl(lastJobId || clip.url.split("/")[2] || "", idx, "srt")}
                      download={`clip_${idx + 1}.srt`}
                      style={{
                        padding: "0.45rem 0.75rem",
                        borderRadius: "6px",
                        background: "#0f172a",
                        color: "#94a3b8",
                        textDecoration: "none",
                        fontSize: "0.8rem",
                        border: "1px solid #334155",
                      }}
                    >
                      .SRT
                    </a>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Direct Publish Modal in OneClickAI */}
      {publishModalClip && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, background: "rgba(0,0,0,0.8)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000, backdropFilter: "blur(4px)" }}>
          <div style={{ background: "#1e293b", border: "1px solid #334155", borderRadius: "16px", padding: "2rem", width: "90%", maxWidth: "600px", maxHeight: "90vh", overflowY: "auto", boxShadow: "0 20px 40px rgba(0,0,0,0.6)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1.25rem" }}>
              <h2 style={{ fontSize: "1.25rem", fontWeight: "700", color: "#f8fafc", margin: 0 }}>
                🚀 Publish {modalUploadMode === "shorts" ? "Short" : "Video"} to YouTube
              </h2>
              <button onClick={() => setPublishModalClip(null)} style={{ background: "transparent", border: "none", color: "#94a3b8", fontSize: "1.5rem", cursor: "pointer" }}>✕</button>
            </div>

            {modalError && (
              <div style={{ padding: "0.75rem", borderRadius: "8px", background: "rgba(239,68,68,0.2)", border: "1px solid #ef4444", color: "#fca5a5", fontSize: "0.85rem", marginBottom: "1rem" }}>
                {modalError}
              </div>
            )}

            {uploadSuccess ? (
              <div style={{ textAlign: "center", padding: "1.5rem 0" }}>
                <div style={{ fontSize: "3rem", marginBottom: "0.5rem" }}>🎉</div>
                <h3 style={{ fontSize: "1.2rem", fontWeight: "700", color: "#00d29d", marginBottom: "0.5rem" }}>
                  Published to YouTube!
                </h3>
                <p style={{ color: "#cbd5e1", fontSize: "0.9rem", marginBottom: "1.5rem" }}>"{uploadSuccess.title}"</p>
                <div style={{ display: "flex", gap: "1rem", justifyContent: "center" }}>
                  <a href={uploadSuccess.url} target="_blank" rel="noreferrer" style={{ padding: "0.75rem 1.5rem", borderRadius: "8px", background: "#ef4444", color: "#fff", textDecoration: "none", fontWeight: "700", fontSize: "0.9rem" }}>
                    Watch on YouTube ↗
                  </a>
                  <button onClick={() => setPublishModalClip(null)} style={{ padding: "0.75rem 1.5rem", borderRadius: "8px", background: "#334155", color: "#fff", border: "none", fontWeight: "600", cursor: "pointer" }}>
                    Done
                  </button>
                </div>
              </div>
            ) : (
              <div>
                {/* Channel Selector */}
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1", marginBottom: "0.4rem" }}>Target Channel</label>
                  <select
                    value={publishChannelId}
                    onChange={(e) => setPublishChannelId(e.target.value)}
                    disabled={isUploadingToYT}
                    style={{ width: "100%", padding: "0.65rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.9rem" }}
                  >
                    {channels.map((ch) => (
                      <option key={ch.id} value={ch.id}>{ch.title} ({ch.youtube_channel_id})</option>
                    ))}
                  </select>
                </div>

                {/* Title */}
                <div style={{ marginBottom: "1rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "0.3rem" }}>
                    <label style={{ fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1" }}>Title</label>
                    <span style={{ fontSize: "0.75rem", color: "#94a3b8" }}>{publishTitle.length} / {modalUploadMode === "shorts" ? 60 : 100}</span>
                  </div>
                  <input
                    type="text"
                    value={publishTitle}
                    onChange={(e) => setPublishTitle(e.target.value)}
                    maxLength={modalUploadMode === "shorts" ? 60 : 100}
                    disabled={isUploadingToYT}
                    style={{ width: "100%", padding: "0.65rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.9rem", boxSizing: "border-box" }}
                  />
                  {aiTitles.length > 0 && (
                    <div style={{ marginTop: "0.4rem", display: "flex", flexDirection: "column", gap: "0.3rem" }}>
                      <span style={{ fontSize: "0.72rem", color: "#94a3b8" }}>AI Suggestions:</span>
                      {aiTitles.map((t, i) => (
                        <button key={i} type="button" onClick={() => setPublishTitle(t)} style={{ padding: "0.3rem 0.5rem", borderRadius: "4px", background: publishTitle === t ? "#00d29d" : "#334155", color: publishTitle === t ? "#0f172a" : "#e2e8f0", border: "none", cursor: "pointer", fontSize: "0.75rem", textAlign: "left" }}>
                          {i + 1}. {t}
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                {/* Description */}
                <div style={{ marginBottom: "1rem" }}>
                  <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1", marginBottom: "0.3rem" }}>Description</label>
                  <textarea
                    rows={3}
                    value={publishDesc}
                    onChange={(e) => setPublishDesc(e.target.value)}
                    disabled={isUploadingToYT}
                    style={{ width: "100%", padding: "0.65rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.85rem", resize: "vertical", boxSizing: "border-box" }}
                  />
                </div>

                {/* Tags & Privacy */}
                <div style={{ display: "grid", gridTemplateColumns: "1.2fr 0.8fr", gap: "0.75rem", marginBottom: "1.25rem" }}>
                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1", marginBottom: "0.3rem" }}>Hashtags</label>
                    <input
                      type="text"
                      value={publishTags}
                      onChange={(e) => setPublishTags(e.target.value)}
                      disabled={isUploadingToYT}
                      style={{ width: "100%", padding: "0.65rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.85rem", boxSizing: "border-box" }}
                    />
                  </div>
                  <div>
                    <label style={{ display: "block", fontSize: "0.85rem", fontWeight: "600", color: "#cbd5e1", marginBottom: "0.3rem" }}>Visibility</label>
                    <select
                      value={publishPrivacy}
                      onChange={(e) => setPublishPrivacy(e.target.value)}
                      disabled={isUploadingToYT}
                      style={{ width: "100%", padding: "0.65rem", borderRadius: "8px", background: "#0f172a", border: "1px solid #334155", color: "#fff", fontSize: "0.85rem" }}
                    >
                      <option value="public">Public</option>
                      <option value="unlisted">Unlisted</option>
                      <option value="private">Private</option>
                    </select>
                  </div>
                </div>

                <div style={{ display: "flex", gap: "0.75rem", justifyContent: "flex-end" }}>
                  <button type="button" onClick={() => setPublishModalClip(null)} disabled={isUploadingToYT} style={{ padding: "0.65rem 1.25rem", borderRadius: "8px", background: "#334155", color: "#fff", border: "none", cursor: "pointer", fontWeight: "600" }}>Cancel</button>
                  <button
                    type="button"
                    onClick={handleExecuteUpload}
                    disabled={isUploadingToYT || channels.length === 0}
                    style={{
                      padding: "0.65rem 1.5rem",
                      borderRadius: "8px",
                      background: isUploadingToYT ? "#475569" : (modalUploadMode === "shorts" ? "#ef4444" : "#3b82f6"),
                      color: "#fff",
                      border: "none",
                      cursor: (isUploadingToYT || channels.length === 0) ? "not-allowed" : "pointer",
                      fontWeight: "700",
                    }}
                  >
                    {isUploadingToYT ? "Uploading..." : `Upload as ${modalUploadMode === "shorts" ? "Short" : "Video"}`}
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
