"use client";
import { useState, useRef, useEffect } from "react";

const STAGES = [
  {
    id: "monitor",
    num: "01",
    name: "Monitor",
    timing: "0–∞ s",
    detail: "Polls edge switch s1 PacketIn rate and controller A CPU every second via OVS port stats and psutil.",
  },
  {
    id: "detect",
    num: "02",
    name: "Detect",
    timing: "~3 s",
    detail: "Both signals exceed threshold (>1,500 pkt/s AND >70% CPU) for 3 consecutive samples.",
  },
  {
    id: "isolate",
    num: "03",
    name: "Isolate",
    timing: "~0.1 s",
    detail: "SIGKILL the saturated ryu-manager A process — clearing the unbounded event-queue. Immediately respawn.",
  },
  {
    id: "prevent",
    num: "04",
    name: "Prevent",
    timing: "~60 s",
    detail: "Install OpenFlow Meter on s1: rate=100 pkt/s for 60 seconds, before controller reconnects.",
  },
  {
    id: "verify",
    num: "05",
    name: "Verify",
    timing: "~13 s",
    detail: "Poll GET /stats/switches until the restarted controller responds. Meter expires automatically.",
  },
];

export function CircuitBreakerPipeline() {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const [running, setRunning]     = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const replay = () => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.matches || running) return;
    setRunning(true);
    setActiveIdx(0);
    let i = 0;
    const step = () => {
      i++;
      if (i < STAGES.length) {
        setActiveIdx(i);
        timer.current = setTimeout(step, 800);
      } else {
        setRunning(false);
        setActiveIdx(null);
      }
    };
    timer.current = setTimeout(step, 800);
  };

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  return (
    <div>
      <div className="pipeline" role="list" aria-label="Circuit breaker pipeline stages">
        {STAGES.map((stage, i) => (
          <div
            key={stage.id}
            className="pipeline-stage"
            role="listitem"
            style={{
              background: activeIdx === i ? "var(--bg-elevated)" : "var(--bg-surface)",
              borderTop: activeIdx === i ? "2px solid var(--accent)" : "2px solid transparent",
            }}
          >
            <div className="pipeline-stage-num">Stage {stage.num}</div>
            <div
              className={`pipeline-stage-name${activeIdx === i ? " active-stage" : ""}`}
            >
              {stage.name}
            </div>
            <div className="pipeline-stage-desc">{stage.detail}</div>
            <div style={{
              marginTop: "0.55rem",
              fontFamily: "var(--font-jetbrains-mono, monospace)",
              fontSize: "0.67rem",
              color: "var(--text-muted)",
            }}>
              {stage.timing}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <button
          id="replay-pipeline"
          className="btn btn-secondary"
          onClick={replay}
          disabled={running}
          aria-label="Replay circuit breaker animation"
          style={{ fontSize: "0.82rem", padding: "0.45rem 0.9rem" }}
        >
          {running ? "Running…" : "▶ Replay"}
        </button>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          Total ~16.7 s · preliminary testbed measurement
        </span>
      </div>

      <div className="callout warning" style={{ marginTop: "1.25rem" }}>
        <div className="callout-title">Preliminary</div>
        <p>
          The ~16.7 s figure includes: 3 s detection, ~0.1 s SIGKILL/respawn, ~13 s
          health-check polling. Measured in one Mininet run at 5,000 pkt/s. Results may vary.
        </p>
      </div>
    </div>
  );
}
