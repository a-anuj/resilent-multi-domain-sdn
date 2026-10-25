import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Future Work",
  description: "Planned extensions: ML-based detection, live flow migration, authenticated East-West protocol, distributed circuit breaker.",
};

const ITEMS = [
  {
    id: "ml",
    num: "01",
    title: "ML-Based Anomaly Detection",
    color: "var(--cyan)",
    status: "Not started",
    motivation: `The current dual-signal threshold detector cannot detect "Low and Slow" attacks — sustained low-rate flooding that stays just below the static CPU and PacketIn thresholds but still degrades controller performance over time.`,
    approach: "Replace or augment static thresholds with a supervised ML classifier (Random Forest or SVM) trained on rolling time-series features.",
    features: [
      "PacketIn rate (5 s rolling average) — smooths transient spikes",
      "CPU variance — tracks instability, not just level",
      "Context switch rate — correlates with event-loop thrashing",
      "E-W sync message frequency — detects degradation in inter-controller communication",
    ],
    note: "The repository's generate_results.py includes placeholder charts illustrating anticipated precision/recall improvement. The actual ML model has not been trained or evaluated.",
  },
  {
    id: "migration",
    num: "02",
    title: "Live Flow Migration",
    color: "var(--blue)",
    status: "Not started",
    motivation: "The current mitigation kills and restarts the controller, briefly interrupting forwarding for all flows in the affected domain during recovery (~1–2 s of forwarding on stale or expired flow entries).",
    approach: "Before killing the saturated controller, transfer active flow state to a standby or adjacent domain controller that takes over forwarding during recovery — seamless failover with no traffic interruption.",
    features: [
      "State-transfer protocol between controllers (not natively in OpenFlow)",
      "Pre-provisioned standby controller synchronized via E-W",
      "Possible use of IETF ALTO-like mechanisms for state handoff",
    ],
    note: "OpenFlow does not natively support controller handoff. Custom state-transfer extensions or external state storage would be required.",
  },
  {
    id: "auth",
    num: "03",
    title: "Authenticated East-West Protocol",
    color: "var(--amber)",
    status: "Not started",
    motivation: "The current E-W REST protocol is unauthenticated. Any process on the network can send crafted JSON payloads to the /update endpoint — enabling the Topology Poisoning attack.",
    approach: "Add authentication at the message and transport layers.",
    features: [
      "HMAC-SHA256 signatures on all E-W messages",
      "TLS 1.3 for all inter-controller connections",
      "Pre-shared keys (simple) or PKI (scalable) for key management",
    ],
    note: "Topology Poisoning would require a compromised controller private key, dramatically raising the attack cost. This is identified as a known security gap in the current implementation.",
  },
  {
    id: "distributed",
    num: "04",
    title: "Distributed Circuit Breaker",
    color: "var(--mint)",
    status: "Not started",
    motivation: "The current circuit breaker monitors and protects Domain A only. A coordinated multi-domain attack — flooding all three domains simultaneously — would defeat the single-domain daemon.",
    approach: "Deploy a circuit breaker daemon in each domain, with a lightweight consensus protocol coordinating across domains.",
    features: [
      "Each domain daemon independently monitors its controller",
      "Detection decisions shared across domains (prevents conflicting simultaneous restarts)",
      "Coordinator daemon aggregates multi-domain signals",
      "Recovery actions sequenced — only one domain recovers at a time to avoid full-network outage",
    ],
    note: "The inter-daemon coordination channel must remain available even when controllers are killed. Consensus in the presence of network partitions (which the attack itself may cause) is a core challenge.",
  },
];

export default function FutureWorkPage() {
  return (
    <div className="docs-layout">
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {ITEMS.map((item) => (
            <li key={item.id} className="sidebar-nav-item">
              <a href={`#${item.id}`}>{item.title}</a>
            </li>
          ))}
        </ul>
      </aside>

      <article className="docs-article" aria-labelledby="fw-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="fw-title">Future Work</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Planned extensions identified in the project presentation.{" "}
            <strong style={{ color: "var(--coral)" }}>None of these are currently implemented.</strong>
          </p>
        </div>

        <div className="callout info" style={{ marginBottom: "2rem" }}>
          <div className="callout-title">Status Note</div>
          <p>
            All items on this page are planned extensions, not completed capabilities. They
            are presented as directions for continued research and development beyond the
            current project scope.
          </p>
        </div>

        {ITEMS.map((item) => (
          <section key={item.id} id={item.id} aria-labelledby={`${item.id}-h`} style={{ marginBottom: "3rem" }}>
            <h2 id={`${item.id}-h`} style={{ display: "flex", alignItems: "center", gap: "0.75rem", flexWrap: "wrap" }}>
              <span style={{ fontFamily: "var(--font-jetbrains-mono, monospace)", fontSize: "0.75rem", color: item.color }}>
                {item.num}
              </span>
              {item.title}
              <span className="badge future" style={{ fontSize: "0.65rem" }}>{item.status}</span>
            </h2>
            <h3 style={{ color: "var(--text-secondary)", fontSize: "0.95rem", fontWeight: 400, marginBottom: "1rem" }}>Motivation</h3>
            <p>{item.motivation}</p>
            <h3 style={{ color: "var(--text-secondary)", fontSize: "0.95rem", fontWeight: 400, marginBottom: "0.75rem", marginTop: "1rem" }}>Proposed Approach</h3>
            <p>{item.approach}</p>
            <ul style={{ marginTop: "0.5rem" }}>
              {item.features.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
            <div className="callout warning" style={{ marginTop: "1rem" }}>
              <div className="callout-title">Key Challenge</div>
              <p>{item.note}</p>
            </div>
          </section>
        ))}

        <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <Link href="/docs/contributions" className="btn btn-primary">Novel Contributions →</Link>
          <Link href="/docs" className="btn btn-secondary">All Documentation →</Link>
        </div>
      </article>
    </div>
  );
}
