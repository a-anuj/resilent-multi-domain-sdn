import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Objectives & Scope",
  description: "Four research objectives and clearly separated implemented scope vs. planned future work.",
};

const IMPLEMENTED = [
  "9-switch / 3-domain Mininet topology",
  "Ryu OpenFlow controllers (×3)",
  "REST-based East-West protocol",
  "Global topology registry",
  "Congestion-aware Dijkstra TE",
  "PacketIn Flood attack module",
  "East-West REST Flood attack module",
  "Topology Poisoning attack module",
  "Dual-signal circuit breaker daemon",
  "Out-of-band controller kill + restart",
  "Hardware-level OFMeter rate-limiting",
  "Automated evaluation pipeline",
];

const FUTURE = [
  { item: "ML-based detection (Random Forest / SVM)", href: "/docs/future-work#ml" },
  { item: "Live flow migration during controller recovery", href: "/docs/future-work#migration" },
  { item: "Authenticated E-W protocol (HMAC-SHA256 / TLS 1.3)", href: "/docs/future-work#auth" },
  { item: "Distributed circuit breaker across all domains", href: "/docs/future-work#distributed" },
];

export default function ObjectivesPage() {
  return (
    <div className="docs-layout">
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {[
            { href: "#objectives", label: "Research Objectives" },
            { href: "#implemented", label: "Implemented Scope" },
            { href: "#future", label: "Future Work" },
            { href: "#boundaries", label: "Scope Boundaries" },
          ].map((item) => (
            <li key={item.href} className="sidebar-nav-item">
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>
      </aside>

      <article className="docs-article" aria-labelledby="obj-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="obj-title">Objectives &amp; Scope</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Four research objectives from the presentation, implemented capabilities,
            and clearly labelled future work not yet built.
          </p>
        </div>

        <section id="objectives" aria-labelledby="obj-h">
          <h2 id="obj-h">Research Objectives</h2>
          {[
            {
              num: "01", color: "var(--cyan)",
              title: "Multi-Domain SDN Testbed",
              desc: "Replicate a realistic multi-domain SDN environment using Mininet and Ryu controllers — a 9-switch, 3-domain topology with an operational East-West synchronization protocol and traffic engineering capability.",
            },
            {
              num: "02", color: "var(--blue)",
              title: "Traffic Engineering Implementation",
              desc: "Implement congestion-aware traffic engineering using a Dijkstra-based path selector that reacts to real-time link utilization across domain boundaries, automatically rerouting flows when any link exceeds 70% utilization.",
            },
            {
              num: "03", color: "var(--amber)",
              title: "Offensive Security Evaluation",
              desc: "Execute and characterize attack scenarios (PacketIn flood, East-West REST flood, Topology Poisoning) to systematically measure how each attack degrades network convergence, controller CPU, and latency in the testbed.",
            },
            {
              num: "04", color: "var(--mint)",
              title: "Automated Circuit Breaker Defense",
              desc: "Develop a resilient out-of-band defense mechanism that automatically detects, isolates, and recovers a saturated controller in under 20 seconds without requiring manual administrative intervention.",
            },
          ].map((o) => (
            <div key={o.num} className="card" style={{ marginBottom: "1rem", borderLeftColor: o.color, borderLeftWidth: 3 }}>
              <div style={{ fontFamily: "var(--font-jetbrains-mono, monospace)", fontSize: "0.7rem", color: o.color, marginBottom: "0.4rem", letterSpacing: "0.1em" }}>
                OBJECTIVE {o.num}
              </div>
              <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>{o.title}</h3>
              <p style={{ fontSize: "0.9rem", margin: 0 }}>{o.desc}</p>
            </div>
          ))}
        </section>

        <section id="implemented" aria-labelledby="impl-h">
          <h2 id="impl-h">Implemented Scope</h2>
          <p>The following capabilities were implemented and tested:</p>
          <ul>
            {IMPLEMENTED.map((item) => (
              <li key={item} style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", marginBottom: "0.4rem" }}>
                <span style={{ color: "var(--mint)", flexShrink: 0, marginTop: "0.1rem" }}>✓</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </section>

        <section id="future" aria-labelledby="fut-h">
          <h2 id="fut-h">Future Work — Not Yet Implemented</h2>
          <div className="callout info">
            <div className="callout-title">Planned Extensions</div>
            <p>The following are identified in the presentation as planned future work. None are currently operational.</p>
          </div>
          <ul>
            {FUTURE.map((f) => (
              <li key={f.item} style={{ display: "flex", alignItems: "flex-start", gap: "0.5rem", marginBottom: "0.4rem" }}>
                <span style={{ color: "var(--blue)", flexShrink: 0, marginTop: "0.1rem" }}>⬜</span>
                <Link href={f.href} style={{ fontSize: "0.9rem" }}>{f.item}</Link>
              </li>
            ))}
          </ul>
        </section>

        <section id="boundaries" aria-labelledby="bound-h">
          <h2 id="bound-h">Scope Boundaries and Caveats</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Aspect</th><th>Status</th></tr></thead>
              <tbody>
                <tr><td>Hardware testbed</td><td>Out of scope — Mininet emulation only</td></tr>
                <tr><td>Production-scale topology</td><td>Out of scope — 9 switches, ~12 hosts only</td></tr>
                <tr><td>Statistical rigor</td><td>Not applied — limited trial count, no confidence intervals</td></tr>
                <tr><td>E-W authentication</td><td>Identified limitation — future work</td></tr>
                <tr><td>Cross-controller compatibility</td><td>Ryu-only — other controllers not tested</td></tr>
                <tr><td>Multi-domain simultaneous attack</td><td>Single-domain circuit breaker only</td></tr>
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <Link href="/architecture" className="btn btn-primary">Architecture →</Link>
            <Link href="/docs/future-work" className="btn btn-secondary">Future Work →</Link>
          </div>
        </section>
      </article>
    </div>
  );
}
