import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Documentation",
  description:
    "Full documentation index: problem, objectives, architecture, methodology, results, technical decisions, future work, contributions, and references.",
};

const SECTIONS = [
  {
    group: "Research",
    items: [
      { href: "/docs/problem", title: "Problem & Motivation", desc: "SDN control-plane saturation, PacketIn floods, and why standard mitigations fail." },
      { href: "/docs/objectives", title: "Objectives & Scope", desc: "Four research objectives, implemented capabilities, and out-of-scope items." },
      { href: "/docs/contributions", title: "Novel Contributions", desc: "Event-queue root cause, out-of-band recovery, dual-signal detection, hardware throttling, cross-domain TE." },
      { href: "/docs/future-work", title: "Future Work", desc: "ML detection, live flow migration, authenticated E-W, distributed circuit breaker." },
      { href: "/docs/references", title: "References", desc: "Bibliographic references from the project presentation." },
    ],
  },
  {
    group: "Technical",
    items: [
      { href: "/architecture", title: "Architecture", desc: "9-switch topology, domain details, E-W protocol, and circuit breaker pipeline." },
      { href: "/methodology", title: "Methodology", desc: "Testbed setup, TE formulation, attack suite, detection parameters, and mitigation design." },
      { href: "/docs/decisions", title: "Technical Decisions", desc: "Why Dijkstra, edge-weight math, dual-signal decision rule, parameter trade-offs." },
      { href: "/docs/progress", title: "Implementation Progress", desc: "Phase-by-phase status of testbed, TE, attack suite, and circuit breaker." },
    ],
  },
  {
    group: "Results",
    items: [
      { href: "/results", title: "Results & Evaluation", desc: "Phase 4/5/6 measurements, false-positive characterization, evidence interpretation." },
    ],
  },
];

export default function DocsPage() {
  return (
    <>
      <div style={{ background: "var(--bg-surface)", borderBottom: "1px solid var(--border)", padding: "3rem 0" }}>
        <div className="container">
          <p className="section-eyebrow">Documentation</p>
          <h1 style={{ marginBottom: "0.75rem" }}>All Documentation</h1>
          <p style={{ color: "var(--text-secondary)", maxWidth: "600px" }}>
            Complete research documentation for the Resilient Multi-Domain SDN project.
            Select a section to read, or use the navigation above.
          </p>
        </div>
      </div>

      <div className="container" style={{ padding: "3rem 1.5rem" }}>
        {SECTIONS.map((group) => (
          <section key={group.group} style={{ marginBottom: "3rem" }}>
            <h2 style={{ fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--cyan)", marginBottom: "1.25rem", fontFamily: "var(--font-jetbrains-mono, monospace)" }}>
              {group.group}
            </h2>
            <div className="card-grid">
              {group.items.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  style={{ textDecoration: "none" }}
                >
                  <div className="card" style={{ height: "100%", cursor: "pointer" }}>
                    <h3 style={{ fontSize: "1rem", marginBottom: "0.5rem", color: "var(--text-primary)" }}>
                      {item.title}
                    </h3>
                    <p style={{ fontSize: "0.875rem", margin: 0 }}>{item.desc}</p>
                    <div style={{ marginTop: "1rem", fontSize: "0.8rem", color: "var(--cyan)" }}>Read →</div>
                  </div>
                </Link>
              ))}
            </div>
          </section>
        ))}

        <div className="callout info">
          <div className="callout-title">Repository</div>
          <p>
            Source code, experimental data, and figures are available at{" "}
            <a href="https://github.com/a-anuj/resilent-multi-domain-sdn" target="_blank" rel="noopener noreferrer">
              github.com/a-anuj/resilent-multi-domain-sdn
            </a>.
          </p>
        </div>
      </div>
    </>
  );
}
