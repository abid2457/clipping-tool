// Thin API client for the FastAPI backend. All paths are proxied by Vite in dev
// (see vite.config.js) so these are plain same-origin fetches.

async function jget(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

async function jpost(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `${path} → ${r.status}`);
  return data;
}

export const api = {
  health: () => jget("/health"),
  modelStatus: () => jget("/api/model-status"),
  devices: () => jget("/api/devices"),
  captionStyles: () => jget("/api/caption-styles"),
  fonts: () => jget("/api/fonts"),
  history: () => jget("/api/history"),
  generate: (payload) => jpost("/api/generate", payload),
  cancel: (jobId) => jpost(`/api/cancel/${jobId}`, {}),
  musicSuggest: (sourceId, language) => jget(`/api/music-suggest/${sourceId}` + (language ? `?language=${encodeURIComponent(language)}` : "")),
  transcript: (sourceId, language) => jget(`/api/transcript/${sourceId}` + (language ? `?language=${encodeURIComponent(language)}` : "")),
  result: (jobId) => jget(`/api/result/${jobId}`),
  prefetch: (video_url) => jpost("/api/prefetch", { video_url }),
  prefetchStatus: (id) => jget(`/api/prefetch/${id}`),
  pretranscribe: (source_id, device, language) => jpost("/api/pretranscribe", { source_id, device, language }),
  pretranscribeStatus: (id) => jget(`/api/pretranscribe/${id}`),
  deleteClip: async (clipId, index) => {
    const r = await fetch(`/api/clip/${clipId}/${index}`, { method: "DELETE" });
    return r.ok;
  },
  clipSourceUrl: (clipId, index) => `/api/clip/${clipId}/${index}/source`,
  reframeInfo: (clipId, index) => jget(`/api/clip/${clipId}/${index}/reframe`),
  reframeClip: (clipId, index, keyframes) => jpost(`/api/clip/${clipId}/${index}/reframe`, { keyframes }),
  music: () => jget("/api/music"),
  uploadMusic: async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/music/upload", { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "Music upload failed.");
    return d; // { name, file }
  },
  uploadFont: async (file) => {
    const fd = new FormData();
    fd.append("file", file);
    const r = await fetch("/api/fonts/upload", { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || "Font upload failed.");
    return d; // { family, file }
  },
  upload: async (file, onProgress) =>
    new Promise((resolve, reject) => {
      const fd = new FormData();
      fd.append("file", file);
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
      };
      xhr.onload = () => {
        let d = {};
        try { d = JSON.parse(xhr.responseText); } catch {}
        if (xhr.status === 200 && d.upload_id) resolve(d);
        else reject(new Error(d.detail || "Upload failed."));
      };
      xhr.onerror = () => reject(new Error("Upload failed — network error."));
      xhr.send(fd);
    }),

  // ClipForge v2.0 API additions
  getOAuthUrl: () => jget("/api/v2/oauth/url"),
  youtubeChannels: () => jget("/api/v2/youtube/channels"),
  youtubeQuota: () => jget("/api/v2/youtube/quota"),
  uploadToYouTube: (payload) => jpost("/api/v2/youtube/upload", payload),
  generateMetadata: (transcript, duration) => jpost("/api/v2/metadata/generate", { transcript, duration }),
  generateMetadataV2: (transcript, duration, upload_mode, language, topic) =>
    jpost("/api/v2/metadata/generate-v2", { transcript, duration, upload_mode, language, topic }),
  uploadToYouTubeV2: (payload) => jpost("/api/v2/youtube/upload-v2", payload),
  regenerateTitles: (transcript, duration, upload_mode) =>
    jpost("/api/v2/metadata/regenerate-titles", { transcript, duration, upload_mode }),
  regenerateDesc: (transcript, duration, upload_mode) =>
    jpost("/api/v2/metadata/regenerate-description", { transcript, duration, upload_mode }),
  clipInfo: (clipId, index) => jget(`/api/v2/clip/${clipId}/${index}/info`),
  agentConfigs: () => jget("/api/v2/agent/configs"),
  saveAgentConfig: (payload) => jpost("/api/v2/agent/configs", payload),
  watchedSources: () => jget("/api/v2/agent/watched-sources"),
  scanWatchedSources: () => jpost("/api/v2/agent/scan", {}),
  publishingQueue: () => jget("/api/v2/publishing/queue"),
  approveClip: (clipId, channelId, privacyStatus = "private") =>
    jpost(`/api/v2/publishing/${clipId}/approve?privacy_status=${privacyStatus}` + (channelId ? `&channel_id=${channelId}` : ""), {}),
  rejectClip: (clipId) => jpost(`/api/v2/publishing/${clipId}/reject`, {}),
  updateTranscript: (jobId, words) =>
    fetch(`/api/job/${jobId}/transcript`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ words }),
    }).then((r) => r.json()),
  subtitleUrl: (clipId, index, format = "srt") => `/api/clip/${clipId}/${index}/subtitles?format=${format}`,
};

// Subscribe to a job's Server-Sent Events. Returns a close() fn.
export function streamProgress(jobId, onSnap, onError) {
  const es = new EventSource(`/api/progress/${jobId}`);
  es.onmessage = (ev) => {
    try { onSnap(JSON.parse(ev.data)); } catch {}
  };
  es.onerror = async () => {
    es.close();
    // Fall back to a one-shot result fetch so we don't lose the final state.
    try {
      const r = await fetch(`/api/result/${jobId}`);
      if (r.ok) { onSnap(await r.json()); return; }
    } catch {}
    if (onError) onError();
  };
  return () => es.close();
}
