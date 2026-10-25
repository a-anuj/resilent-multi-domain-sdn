"use client";
import { useState, useRef, useEffect } from "react";

const STAGES = [
  {
    id: "monitor",
    num: "01",
    name: "Monitor",
    color: "var(--cyan)",
    timing: "0–∞ s",
    detail: "Polls edge switch s1 PacketIn rate and controller A CPU% once per second via OVS port stats and psutil.",
  },
  {
    id: "detect",
    num: "02",
    name: "Detect",
    color: "var(--coral)",
    timing: "~3 s",
    detail: "Both signals exceed threshold (>1,500 pkt/s AND >70% CPU) for 3 consecutive samples. Dual-signal prevents false positives.",
  },
  {
    id: "isolate",
    num: "03",
    name: "Isolate",
    color: "var(--amber)",
    timing: "~0.1 s",
    detail: "SIGKILL the poisoned ryu-manager A process — instantly clearing the unbounded event-queue backlog. Immediately respawn.",
  },
  {
    id: "prevent",
    num: "04",
    name: "Prevent",
    color: "var(--blue)",
    timing: "~60 s",
    detail: "Install OpenFlow Meter on s1 via ovs-ofctl: band=type=drop, rate=100 pkt/s for 60 seconds, before controller reconnects.",
  },
  {
    id: "verify",
    num: "05",
    name: "Verify",
    color: "var(--mint)",
    timing: "~13 s",
    detail: "Poll GET /stats/switches on the restarted controller. Success confirms reconnection. Meter expires automatically at 60 s.",
  },
];

export function CircuitBreakerPipeline() {
  const [active, setActive] = useState<number | null>(null);
  const [animating, setAnimating] = useState(false);
  const [signalPos, setSignalPos] = useState(0);
  const animRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runAnimation = () => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (mq.matches) return;
    if (animating) return;
    setAnimating(true);
    setSignalPos(0);
    setActive(0);
    let i = 0;
    const step = () => {
      i++;
      if (i < STAGES.length) {
        setActive(i);
        setSignalPos(i);
        animRef.current = setTimeout(step, 900);
      } else {
        setAnimating(false);
        setActive(null);
        setSignalPos(-1);
      }
    };
    animRef.current = setTimeout(step, 900);
  };

  useEffect(() => {
    return () => { if (animRef.current) clearTimeout(animRef.current); };
  }, []);

  return (
    <div>
      <div
        className="pipeline"
        role="list"
        aria-label="Circuit breaker pipeline stages"
      >
        {STAGES.map((stage, i) => (
          <div
            key={stage.id}
            className={`pipeline-stage ${stage.id}`}
            role="listitem"
            style={{
              borderColor: active === i ? stage.color : "var(--border)",
              background: active === i ? `color-mix(in srgb, ${stage.color} 8%, var(--bg-surface))` : "var(--bg-surface)",
              transition: "border-color 0.3s, background 0.3s",
            }}
          >
            <div className="pipeline-stage-num">Stage {stage.num}</div>
            <div className="pipeline-stage-name" style={{ color: stage.color }}>{stage.name}</div>
            <div className="pipeline-stage-desc">{stage.detail}</div>
            <div style={{ marginTop: "0.6rem", fontFamily: "var(--font-jetbrains-mono, monospace)", fontSize: "0.7rem", color: "var(--text-muted)" }}>
              {stage.timing}
            </div>
          </div>
        ))}
      </div>

      <div style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <button
          id="replay-circuit-breaker"
          className="btn btn-secondary"
          onClick={runAnimation}
          disabled={animating}
          aria-label="Replay circuit breaker animation sequence"
          style={{ fontSize: "0.85rem", padding: "0.5rem 1rem" }}
        >
          {animating ? "Animating…" : "▶ Replay sequence"}
        </button>
        <span style={{ fontSize: "0.78rem", color: "var(--text-muted)" }}>
          Total: ~16.7 s end-to-end (preliminary testbed result)
        </span>
      </div>

      <div className="callout warning" style={{ marginTop: "1.5rem" }}>
        <div className="callout-title">Preliminary Result</div>
        <p>
          The ~16.7 s total mitigation time includes the 3 s detection window, ~0.1 s for SIGKILL/respawn,
          and ~13 s for the health-verification polling window. This was measured in one Mininet testbed run
          against a 5,000 pkt/s flood. Results may vary.
        </p>
      </div>
    </div>
  );
}
