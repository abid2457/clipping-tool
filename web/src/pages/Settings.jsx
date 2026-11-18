import { useEffect, useState } from "react";
import { api } from "../api.js";
import logoImg from "../assets/logo.jpg";

export default function Settings() {
  const [d, setD] = useState(null);
  useEffect(() => { api.devices().then(setD).catch(() => setD({ devices: [], cuda_available: false })); }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 640 }}>
      {/* Brand & About Card */}
      <div className="card">
        <div className="card-h">
          <h2>About Tech Hub</h2>
          <span className="badge ok">v2.0 Pro</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "12px 0 18px", borderBottom: "1px solid var(--line)" }}>
          <img src={logoImg} alt="Tech Hub Logo" style={{ width: 56, height: 56, borderRadius: 14, objectFit: "cover", boxShadow: "0 6px 20px -6px var(--accent)" }} />
          <div>
            <div style={{ fontSize: 18, fontWeight: 800, color: "var(--text)" }}>Tech Hub</div>
            <div style={{ fontSize: 12, fontWeight: 700, color: "var(--accent)", textTransform: "uppercase", letterSpacing: "0.06em", marginTop: 2 }}>Created by Barakah Tech</div>
            <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>High-Performance AI Video Clipping, Auto-Reframing & Shorts Studio</div>
          </div>
        </div>
        <div className="row" style={{ justifyContent: "space-between", padding: "12px 0", borderBottom: "1px solid var(--line)" }}>
          <span className="note" style={{ margin: 0 }}>Developer / Brand</span>
          <b>Barakah Tech</b>
        </div>
        <div className="row" style={{ justifyContent: "space-between", padding: "12px 0" }}>
          <span className="note" style={{ margin: 0 }}>Privacy & Execution</span>
          <b style={{ color: "var(--accent)" }}>100% Local Machine (Zero Cloud Audio/Video Leak)</b>
        </div>
      </div>

      {/* Hardware & Compute Card */}
      <div className="card">
        <div className="card-h"><h2>Hardware & Compute</h2></div>
        {!d ? <div className="note">Checking hardware capabilities…</div> : (
          <>
            <div className="row" style={{ justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
              <span className="note" style={{ margin: 0 }}>GPU (CUDA)</span>
              <b>{d.cuda_available ? (d.gpu_name || "Available") : "Not available (CPU Vectorized)"}</b>
            </div>
            <div className="row" style={{ justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid var(--line)" }}>
              <span className="note" style={{ margin: 0 }}>Active Device</span>
              <b>{(d.default || "—").toUpperCase()}</b>
            </div>
            <div className="row" style={{ justifyContent: "space-between", padding: "10px 0" }}>
              <span className="note" style={{ margin: 0 }}>Available Engines</span>
              <b>{(d.devices || []).map((x) => x.toUpperCase()).join(" · ") || "CPU (INT8)"}</b>
            </div>
            <div className="note" style={{ marginTop: 16 }}>
              All models execute directly on your processor using optimized CTranslate2 INT8 instructions.
            </div>
          </>
        )}
      </div>
    </div>
  );
}
