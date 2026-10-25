import type { Metadata } from "next";
import Link from "next/link";
import { ScrollReveal } from "@/components/ScrollReveal";
import { TopologyDiagram } from "@/components/TopologyDiagram";
import { CircuitBreakerPipeline } from "@/components/CircuitBreakerPipeline";

export const metadata: Metadata = {
  title: "Home",
  description:
    "Resilient Multi-Domain SDN: Automated Circuit Breaker for Control-Plane Saturation Defense. Research documentation portal.",
};

const METRICS = [
  { label: "Detection Time", value: "~3.0 s", accent: "cyan", caveat: "preliminary testbed" },
  { label: "Total Mitigation", value: "~16.7 s", accent: "mint", caveat: "preliminary testbed" },
  { label: "Post-Recovery Latency", value: "14.02 ms", accent: "blue", caveat: "vs 13.8 ms baseline" },
  { label: "Baseline Latency", value: "~13.8 ms", accent: "amber", caveat: "no attack" },
];

const OBJECTIVES = [
  {
    num: "01",
    title: "Multi-Domain Testbed",
    desc: "Replicate a realistic 9-switch, 3-domain SDN environment using Mininet and Ryu controllers with East-West synchronization.",
  },
  {
    num: "02",
    title: "Traffic Engineering",
    desc: "Implement congestion-aware Dijkstra routing that automatically reroutes flows when any link exceeds 70% utilization.",
  },
  {
    num: "03",
    title: "Attack Evaluation",
    desc: "Execute and characterize PacketIn flood, East-West REST flood, and Topology Poisoning attacks to measure their degradation.",
  },
  {
    num: "04",
    title: "Automated Circuit Breaker",
    desc: "Develop an out-of-band defense daemon that detects, isolates, and recovers a saturated controller in under 20 seconds.",
  },
];

export default function HomePage() {
  return (
    <>
      {/* Skip link */}
      <a href="#main-content" className="sr-only focus:not-sr-only" style={{ position: "absolute", left: "-9999px" }}>
        Skip to main content
      </a>

      {/* HERO */}
      <section className="hero" aria-labelledby="hero-heading">
        <div className="hero-grid-bg" aria-hidden="true" />
        <div className="hero-glow" aria-hidden="true" />
        <div className="container" style={{ position: "relative", zIndex: 1 }}>
          <div className="hero-badge" aria-label="Research project">
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--cyan)", display: "inline-block" }} aria-hidden="true" />
            Research Project · SDN Security
          </div>

          <h1 id="hero-heading" className="hero-title">
            Resilient Multi-Domain SDN
            <br />
            <span style={{ color: "var(--cyan)" }}>Automated Circuit Breaker</span>
          </h1>

          <p className="hero-subtitle">
            An out-of-band defense system that detects and mitigates control-plane
            saturation in multi-controller SDN — killing and recovering a poisoned
            Ryu controller in ~16.7 s, restoring latency to baseline.
          </p>

          <div className="hero-actions">
            <Link href="/architecture" className="btn btn-primary" id="cta-architecture">
              Explore Architecture
              <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path fillRule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
            </Link>
            <Link href="/methodology" className="btn btn-secondary" id="cta-methodology">
              Read Methodology
            </Link>
            <Link href="/results" className="btn btn-secondary" id="cta-results">
              View Results
            </Link>
            <a
              href="https://github.com/a-anuj/resilent-multi-domain-sdn"
              target="_blank"
              rel="noopener noreferrer"
              className="btn btn-ghost"
              id="cta-github"
              aria-label="Open GitHub repository (opens in new tab)"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
                <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
              </svg>
              GitHub Repository
            </a>
          </div>

          {/* Key metrics strip */}
          <div className="callout warning" style={{ marginBottom: "2rem" }}>
            <div className="callout-title">Evidence caveat</div>
            <p>
              All metrics below are <strong>preliminary testbed results</strong> from a single Mininet
              emulation run. They should not be generalized without repeated trials, confidence
              intervals, and hardware validation.
            </p>
          </div>

          <div className="metric-grid">
            {METRICS.map((m) => (
              <div key={m.label} className={`metric-card ${m.accent}`}>
                <div className="metric-label">{m.label}</div>
                <div className="metric-value">{m.value}</div>
                <div className="metric-sub">{m.caveat}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* TOPOLOGY OVERVIEW */}
      <section className="section" aria-labelledby="topo-heading">
        <div className="container">
          <ScrollReveal>
            <p className="section-eyebrow">Network Topology</p>
            <h2 id="topo-heading" className="section-heading">
              9-Switch, 3-Domain SDN Testbed
            </h2>
            <p className="section-desc">
              Three independent Ryu OpenFlow controllers manage their respective domains,
              connected via a REST-based East-West protocol for topology and link-state
              synchronization.
            </p>
          </ScrollReveal>
          <ScrollReveal>
            <TopologyDiagram />
            <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", marginTop: "0.75rem", textAlign: "center" }}>
              Interactive topology diagram. Hover over domains and links to highlight them.
              Dashed lines indicate inter-domain boundary links; coral dashed line shows the A–C alternate TE path.
            </p>
          </ScrollReveal>

          <ScrollReveal>
            <div className="card-grid" style={{ marginTop: "2.5rem" }}>
              {[
                { domain: "Domain A", color: "var(--cyan)", switches: "s1, s2, s3", controller: "Ryu A — TCP 6633 / REST 8080", role: "Primary attack target in evaluation" },
                { domain: "Domain B", color: "var(--blue)", switches: "s4, s5, s6", controller: "Ryu B — TCP 6634 / REST 8081", role: "Intermediate routing domain" },
                { domain: "Domain C", color: "var(--mint)", switches: "s7, s8, s9", controller: "Ryu C — TCP 6653 / REST 8082", role: "TE alternate path egress" },
              ].map((d) => (
                <div key={d.domain} className="card">
                  <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.75rem" }}>
                    <div style={{ width: 10, height: 10, borderRadius: "50%", background: d.color, flexShrink: 0 }} aria-hidden="true" />
                    <h3 style={{ fontSize: "1rem", margin: 0, color: d.color }}>{d.domain}</h3>
                  </div>
                  <p style={{ fontSize: "0.85rem", margin: "0 0 0.35rem" }}>
                    <strong style={{ color: "var(--text-primary)" }}>Switches:</strong>{" "}
                    <code>{d.switches}</code>
                  </p>
                  <p style={{ fontSize: "0.85rem", margin: "0 0 0.35rem" }}>
                    <strong style={{ color: "var(--text-primary)" }}>Controller:</strong>{" "}
                    <code>{d.controller}</code>
                  </p>
                  <p style={{ fontSize: "0.82rem", color: "var(--text-muted)", margin: 0 }}>{d.role}</p>
                </div>
              ))}
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* PROJECT OBJECTIVES */}
      <section className="section" style={{ background: "var(--bg-surface)", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)" }} aria-labelledby="obj-heading">
        <div className="container">
          <ScrollReveal>
            <p className="section-eyebrow">Research Objectives</p>
            <h2 id="obj-heading" className="section-heading">Four Core Goals</h2>
            <p className="section-desc">
              The project pursues four interconnected research objectives culminating in
              the automated circuit breaker defense system.
            </p>
          </ScrollReveal>
          <div className="card-grid">
            {OBJECTIVES.map((o, i) => (
              <ScrollReveal key={o.num}>
                <div className="card" style={{ height: "100%" }}>
                  <div style={{ fontFamily: "var(--font-jetbrains-mono, monospace)", fontSize: "0.7rem", color: "var(--cyan)", marginBottom: "0.5rem", letterSpacing: "0.1em" }}>
                    OBJECTIVE {o.num}
                  </div>
                  <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>{o.title}</h3>
                  <p style={{ fontSize: "0.88rem", margin: 0 }}>{o.desc}</p>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </div>
      </section>

      {/* CIRCUIT BREAKER PIPELINE */}
      <section className="section" aria-labelledby="pipeline-heading">
        <div className="container">
          <ScrollReveal>
            <p className="section-eyebrow">Defense System</p>
            <h2 id="pipeline-heading" className="section-heading">Circuit Breaker Pipeline</h2>
            <p className="section-desc">
              A four-stage automated response pipeline triggered by dual-signal detection
              of control-plane saturation.
            </p>
          </ScrollReveal>
          <ScrollReveal>
            <CircuitBreakerPipeline />
          </ScrollReveal>
          <ScrollReveal>
            <div style={{ display: "flex", gap: "1rem", marginTop: "2rem", flexWrap: "wrap" }}>
              <Link href="/architecture" className="btn btn-primary">Full Architecture →</Link>
              <Link href="/methodology" className="btn btn-secondary">Methodology Details →</Link>
            </div>
          </ScrollReveal>
        </div>
      </section>

      {/* PROBLEM SUMMARY */}
      <section className="section" style={{ background: "var(--bg-surface)", borderTop: "1px solid var(--border)" }} aria-labelledby="problem-heading">
        <div className="container">
          <ScrollReveal>
            <p className="section-eyebrow">The Problem</p>
            <h2 id="problem-heading" className="section-heading">Why Standard Mitigations Fail</h2>
          </ScrollReveal>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: "2rem" }}>
            <ScrollReveal>
              <div>
                <h3 style={{ marginBottom: "0.75rem", color: "var(--coral)" }}>The Attack</h3>
                <p style={{ fontSize: "0.92rem" }}>
                  A <strong style={{ color: "var(--text-primary)" }}>PacketIn Flood</strong> generates packets with
                  randomized source MAC/IP addresses, causing 100% of packets to trigger
                  table-miss → PacketIn messages to the controller.
                </p>
                <p style={{ fontSize: "0.92rem", marginTop: "0.75rem" }}>
                  At rates up to 5,000 pkt/s, the controller's single-threaded event loop
                  cannot drain the queue fast enough. The queue grows unboundedly,
                  latency spikes to <strong style={{ color: "var(--coral)" }}>&gt;1,350 ms</strong>,
                  and inter-domain synchronization breaks.
                </p>
              </div>
            </ScrollReveal>
            <ScrollReveal>
              <div>
                <h3 style={{ marginBottom: "0.75rem", color: "var(--amber)" }}>Why Flow-Table Flushes Fail</h3>
                <p style={{ fontSize: "0.92rem" }}>
                  The standard response — <code>del-flows</code> — is completely ineffective.
                  The problem is not the flow table; it is the controller&apos;s internal
                  event queue. Flushing the table causes all existing flows to re-trigger
                  PacketIn messages, making the situation <em>worse</em>.
                </p>
                <p style={{ fontSize: "0.92rem", marginTop: "0.75rem" }}>
                  The only way to clear the poisoned queue is to{" "}
                  <strong style={{ color: "var(--mint)" }}>terminate the process</strong>{" "}
                  — which the circuit breaker does via <code>SIGKILL</code>, then immediately
                  respawns a clean controller.
                </p>
              </div>
            </ScrollReveal>
          </div>
          <ScrollReveal>
            <div style={{ marginTop: "2rem" }}>
              <Link href="/docs" className="btn btn-secondary">Read Full Documentation →</Link>
            </div>
          </ScrollReveal>
        </div>
      </section>
    </>
  );
}
