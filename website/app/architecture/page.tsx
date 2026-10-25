import type { Metadata } from "next";
import Link from "next/link";
import { ScrollReveal } from "@/components/ScrollReveal";
import { TopologyDiagram } from "@/components/TopologyDiagram";
import { CircuitBreakerPipeline } from "@/components/CircuitBreakerPipeline";

export const metadata: Metadata = {
  title: "Architecture",
  description:
    "9-switch, 3-domain SDN topology with Ryu controllers, East-West synchronization, and the out-of-band circuit breaker pipeline.",
};

const DOMAIN_DETAILS = [
  {
    domain: "Domain A", color: "var(--cyan)", border: "rgba(56,214,232,0.3)",
    switches: "s1, s2, s3", ofPort: "TCP 6633", restPort: "REST 8080",
    notes: "s1 is the ingress edge switch monitored by the circuit breaker. PacketIn rate is measured at s1.",
  },
  {
    domain: "Domain B", color: "var(--blue)", border: "rgba(91,140,255,0.3)",
    switches: "s4, s5, s6", ofPort: "TCP 6634", restPort: "REST 8081",
    notes: "s4 and s6 are boundary switches connected to Domain A and Domain C respectively.",
  },
  {
    domain: "Domain C", color: "var(--mint)", border: "rgba(82,214,160,0.3)",
    switches: "s7, s8, s9", ofPort: "TCP 6653", restPort: "REST 8082",
    notes: "s8 connects to s1 via the A–C diagonal link used as the TE alternate path in Phase 4 experiments.",
  },
];

const INTER_DOMAIN = [
  { link: "s3 ↔ s4", domains: "A – B", bw: "1,000 Mbps", type: "Boundary" },
  { link: "s6 ↔ s7", domains: "B – C", bw: "1,000 Mbps", type: "Boundary" },
  { link: "s1 ↔ s8", domains: "A – C", bw: "1,000 Mbps", type: "Alternate / TE diagonal" },
];

const EW_ENDPOINTS = [
  { endpoint: "GET /topology", direction: "Any peer → controller", payload: "Full graph: switches, hosts, links" },
  { endpoint: "GET /linkstate", direction: "Any peer → controller", payload: "Port utilization rates (all ports)" },
  { endpoint: "POST /update", direction: "Peer controller push", payload: "Topology / link-state delta" },
];

export default function ArchitecturePage() {
  return (
    <div className="docs-layout">
      {/* Sidebar */}
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {[
            { href: "#topology", label: "Network Topology" },
            { href: "#domains", label: "Domain Details" },
            { href: "#inter-domain", label: "Inter-Domain Links" },
            { href: "#east-west", label: "East-West Protocol" },
            { href: "#circuit-breaker", label: "Circuit Breaker Pipeline" },
            { href: "#out-of-band", label: "Out-of-Band Design" },
          ].map((item) => (
            <li key={item.href} className="sidebar-nav-item">
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>
        <div style={{ marginTop: "2rem", borderTop: "1px solid var(--border)", paddingTop: "1rem" }}>
          <div className="sidebar-nav-title">Quick Links</div>
          <ul className="sidebar-nav-list">
            <li className="sidebar-nav-item"><Link href="/methodology">Methodology →</Link></li>
            <li className="sidebar-nav-item"><Link href="/results">Results →</Link></li>
          </ul>
        </div>
      </aside>

      {/* Main article */}
      <article className="docs-article" aria-labelledby="arch-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="arch-title">Architecture</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            A 9-switch, 3-domain multi-controller SDN testbed using Ryu and Mininet,
            with East-West synchronization and an out-of-band circuit breaker daemon.
          </p>
        </div>

        {/* Topology Diagram */}
        <section id="topology" aria-labelledby="topo-h">
          <h2 id="topo-h">Network Topology</h2>
          <p>
            The testbed implements three independently controlled SDN domains on a single
            Mininet emulation host. All switches are Open vSwitch (OVS) instances running
            OpenFlow 1.3. Backbone links between switches run at <code>1,000 Mbps</code>;
            host-to-switch edge links run at <code>100 Mbps</code> (TCLink).
          </p>
          <ScrollReveal>
            <TopologyDiagram />
          </ScrollReveal>
          <p style={{ fontSize: "0.82rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
            Figure: 9-switch, 3-domain topology. Solid lines: intra-domain links.
            Dashed amber lines: inter-domain boundary links. Dashed coral line: A–C alternate TE path.
            Hover over a domain region to highlight it.
          </p>
        </section>

        {/* Domain Details */}
        <section id="domains" aria-labelledby="domains-h">
          <h2 id="domains-h">Domain Details</h2>
          <div style={{ display: "grid", gap: "1rem" }}>
            {DOMAIN_DETAILS.map((d) => (
              <ScrollReveal key={d.domain}>
                <div className="card" style={{ borderColor: d.border }}>
                  <h3 style={{ color: d.color, marginBottom: "0.75rem", fontSize: "1.05rem" }}>{d.domain}</h3>
                  <div className="table-wrap" style={{ margin: 0, border: "none" }}>
                    <table>
                      <tbody>
                        <tr>
                          <td>Switches</td>
                          <td><code>{d.switches}</code></td>
                        </tr>
                        <tr>
                          <td>OpenFlow port</td>
                          <td><code>{d.ofPort}</code></td>
                        </tr>
                        <tr>
                          <td>REST / E-W port</td>
                          <td><code>{d.restPort}</code></td>
                        </tr>
                        <tr>
                          <td>Notes</td>
                          <td style={{ fontFamily: "var(--font-inter)", fontSize: "0.85rem", color: "var(--text-secondary)" }}>{d.notes}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </ScrollReveal>
            ))}
          </div>
        </section>

        {/* Inter-Domain Links */}
        <section id="inter-domain" aria-labelledby="interdomain-h">
          <h2 id="interdomain-h">Inter-Domain Links</h2>
          <p>
            Three inter-domain links connect the domains. Boundary switches (dashed circles
            in the diagram) handle forwarding between domains. All inter-domain links are
            <code>1,000 Mbps</code> backbone links.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Link</th>
                  <th>Domains</th>
                  <th>Bandwidth</th>
                  <th>Role</th>
                </tr>
              </thead>
              <tbody>
                {INTER_DOMAIN.map((r) => (
                  <tr key={r.link}>
                    <td>{r.link}</td>
                    <td>{r.domains}</td>
                    <td>{r.bw}</td>
                    <td>{r.type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* East-West Protocol */}
        <section id="east-west" aria-labelledby="ew-h">
          <h2 id="ew-h">East-West Synchronization</h2>
          <p>
            Controllers communicate via a custom REST-based East-West (E-W) protocol.
            Each controller exposes three endpoints on its E-W port (8080–8082) and polls
            the other controllers&apos; endpoints at regular intervals.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Endpoint</th>
                  <th>Direction</th>
                  <th>Payload</th>
                </tr>
              </thead>
              <tbody>
                {EW_ENDPOINTS.map((e) => (
                  <tr key={e.endpoint}>
                    <td>{e.endpoint}</td>
                    <td>{e.direction}</td>
                    <td>{e.payload}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            The polled data is merged into a shared <code>global_topology</code> registry
            used by the Traffic Engineering path selector. Boundary port statistics are
            explicitly exchanged to give each controller visibility of cross-domain link
            utilization — a key fix for the TE engine that was initially invisible to
            inter-domain congestion.
          </p>
          <div className="callout info">
            <div className="callout-title">Important Limitation</div>
            <p>
              The E-W protocol operates <strong>without authentication</strong> in the current
              implementation. This is an identified security limitation that enables the
              Topology Poisoning attack. Authenticated E-W (HMAC-SHA256 / TLS 1.3) is planned
              as future work.
            </p>
          </div>
        </section>

        {/* Circuit Breaker Pipeline */}
        <section id="circuit-breaker" aria-labelledby="cb-h">
          <h2 id="cb-h">Circuit Breaker Pipeline</h2>
          <p>
            The automated circuit breaker daemon (<code>defense/circuit_breaker.py</code>)
            runs completely outside the SDN control plane. It uses OS-level process management
            and direct OVS switch commands — not OpenFlow or E-W API calls — making it
            immune to the attack condition it is designed to address.
          </p>
          <ScrollReveal>
            <CircuitBreakerPipeline />
          </ScrollReveal>
        </section>

        {/* Out-of-Band Design */}
        <section id="out-of-band" aria-labelledby="oob-h">
          <h2 id="oob-h">Out-of-Band Design Rationale</h2>
          <p>
            A defense that queries a failing controller&apos;s API would fail precisely when
            intervention is needed. The circuit breaker is therefore architecturally separated:
          </p>
          <ul>
            <li>It does <strong>not</strong> depend on the target controller&apos;s REST API for its decision.</li>
            <li>Detection uses <code>psutil</code> (OS CPU monitoring) and OVS PortStats queries — bypassing the controller entirely.</li>
            <li>Mitigation uses <code>os.kill(pid, SIGKILL)</code> — an OS call that terminates the process regardless of its internal state.</li>
            <li>Prevention uses <code>ovs-ofctl add-meter</code> — a direct OVS command that does not require the controller to be running.</li>
            <li>Verification uses a lightweight <code>/stats/switches</code> endpoint — the earliest available signal that the controller is functional.</li>
          </ul>
          <div className="callout success">
            <div className="callout-title">SIGKILL vs. SIGTERM</div>
            <p>
              A graceful shutdown (<code>SIGTERM</code>) requires the event loop to handle the signal —
              impossible when the queue is saturated. <code>SIGKILL</code> bypasses the event loop
              entirely. The trade-off is loss of in-flight state, which is acceptable because
              that state is already corrupted by the flood.
            </p>
          </div>
          <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <Link href="/methodology" className="btn btn-primary">Read Methodology →</Link>
            <Link href="/results" className="btn btn-secondary">View Results →</Link>
          </div>
        </section>
      </article>
    </div>
  );
}
