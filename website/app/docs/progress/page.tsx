import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Implementation Progress",
  description: "Phase-by-phase implementation status: testbed, East-West protocol, traffic engineering, attack suite, and circuit breaker.",
};

const PHASES = [
  {
    phase: "1–2",
    name: "Infrastructure",
    status: "Complete",
    color: "var(--mint)",
    items: [
      "9-switch, 3-domain Mininet topology (Python API) with TCLink bandwidth constraints",
      "Three independent Ryu OpenFlow 1.3 controller instances",
      "RSTP-enabled OVS switches to prevent STP reconvergence during startup",
      "Ordered startup sequence: RSTP → topology stabilization → controller assignment",
    ],
    files: "topology/",
    challenge: null,
  },
  {
    phase: "3",
    name: "East-West Protocol",
    status: "Complete",
    color: "var(--mint)",
    items: [
      "REST-based E-W API (eastwest/ew_api.py)",
      "/topology and /linkstate endpoints on ports 8080–8082",
      "Global topology registry (eastwest/global_topo.py)",
      "Boundary port statistics exchange for inter-domain TE visibility",
    ],
    files: "eastwest/",
    challenge: "Boundary links were initially invisible to each controller's TE engine. Resolution: explicit boundary port statistics exchange added to the E-W protocol.",
  },
  {
    phase: "4",
    name: "Traffic Engineering",
    status: "Complete",
    color: "var(--mint)",
    items: [
      "Congestion-aware Dijkstra path selector in controllers/ew_controller.py",
      "Edge weight formulation: w(e) = 1/(1−u(e)) for uncongested links; PENALTY for congested",
      "70% utilization congestion threshold",
      "Flow installation with OpenFlow barrier synchronization",
      "Cross-domain path segmentation and coordinated FlowMod installation",
    ],
    files: "controllers/ew_controller.py",
    challenge: null,
  },
  {
    phase: "5",
    name: "Attack Suite",
    status: "Complete",
    color: "var(--mint)",
    items: [
      "attacks/packetin_flood.py: Scapy-based randomized MAC/IP flood (AF_PACKET raw sockets)",
      "East-West REST flood module",
      "Topology poisoning module (crafted JSON payloads to /update endpoint)",
    ],
    files: "attacks/",
    challenge: "Only the PacketIn flood caused controller CPU saturation (>70%) and event-queue saturation. E-W and topology attacks degraded performance without triggering the circuit breaker's CPU signal.",
  },
  {
    phase: "6",
    name: "Circuit Breaker",
    status: "Complete",
    color: "var(--mint)",
    items: [
      "Out-of-band daemon: defense/circuit_breaker.py",
      "Dual-signal monitoring (PacketIn rate + CPU), 3-sample confirmation",
      "SIGKILL + respawn mitigation",
      "ovs-ofctl hardware meter installation (100 pkt/s, 60 s)",
      "/stats/switches health-check endpoint for recovery verification",
      "Automated evaluation pipeline: experiments/circuit_breaker_eval.py",
      "Result plot generation: experiments/generate_results.py",
    ],
    files: "defense/, experiments/",
    challenge: "Initial health-check used /te_path which timed out during recovery. Switching to /stats/switches resolved false-failure reports.",
  },
  {
    phase: "7",
    name: "ML-Based Detection",
    status: "Not started",
    color: "var(--blue)",
    items: [
      "Random Forest / SVM classifier (proposed)",
      "Rolling feature extraction: PacketIn rate, CPU variance, context switches, E-W frequency",
      "Training data collection methodology (not yet designed)",
    ],
    files: "—",
    challenge: null,
  },
];

export default function ProgressPage() {
  return (
    <div className="docs-layout">
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {PHASES.map((p) => (
            <li key={p.phase} className="sidebar-nav-item">
              <a href={`#phase-${p.phase.replace("–", "-")}`}>Phase {p.phase}: {p.name}</a>
            </li>
          ))}
        </ul>
      </aside>

      <article className="docs-article" aria-labelledby="prog-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="prog-title">Implementation Progress</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Phase-by-phase status of the SDN testbed, traffic engineering, attack suite,
            and circuit breaker implementation.
          </p>
        </div>

        {PHASES.map((phase) => (
          <section
            key={phase.phase}
            id={`phase-${phase.phase.replace("–", "-")}`}
            aria-labelledby={`phase-h-${phase.phase.replace("–", "-")}`}
          >
            <h2
              id={`phase-h-${phase.phase.replace("–", "-")}`}
              style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}
            >
              <span style={{ fontFamily: "var(--font-jetbrains-mono, monospace)", fontSize: "0.72rem", color: "var(--text-muted)" }}>
                PHASE {phase.phase}
              </span>
              {phase.name}
              <span className={`badge ${phase.status === "Complete" ? "done" : "future"}`} style={{ fontSize: "0.65rem" }}>
                {phase.status}
              </span>
            </h2>

            <ul>
              {phase.items.map((item) => (
                <li key={item} style={{ fontSize: "0.9rem", marginBottom: "0.4rem" }}>
                  <code style={{ fontSize: "0.82em" }}></code>{item}
                </li>
              ))}
            </ul>

            {phase.files !== "—" && (
              <p style={{ fontSize: "0.85rem", marginTop: "0.5rem" }}>
                <strong style={{ color: "var(--text-primary)" }}>Key files:</strong>{" "}
                <code>{phase.files}</code>
              </p>
            )}

            {phase.challenge && (
              <div className="callout info" style={{ marginTop: "0.75rem" }}>
                <div className="callout-title">Key Challenge Resolved</div>
                <p>{phase.challenge}</p>
              </div>
            )}
          </section>
        ))}

        <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <Link href="/results" className="btn btn-primary">View Results →</Link>
          <Link href="/docs/future-work" className="btn btn-secondary">Future Work →</Link>
        </div>
      </article>
    </div>
  );
}
