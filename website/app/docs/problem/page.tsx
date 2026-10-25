import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Problem & Motivation",
  description: "SDN control-plane saturation, PacketIn floods, and why standard mitigations fail in multi-domain SDN.",
};

export default function ProblemPage() {
  return (
    <div className="docs-layout">
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {[
            { href: "#what-is-sdn", label: "What is SDN?" },
            { href: "#multi-domain", label: "Multi-Domain Architecture" },
            { href: "#vulnerability", label: "The Vulnerability" },
            { href: "#why-fails", label: "Why Mitigations Fail" },
            { href: "#ew-attacks", label: "E-W & Topology Attacks" },
            { href: "#summary", label: "Comparison Summary" },
          ].map((item) => (
            <li key={item.href} className="sidebar-nav-item">
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>
      </aside>

      <article className="docs-article" aria-labelledby="prob-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="prob-title">Problem &amp; Motivation</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Why multi-controller SDN architectures are vulnerable to control-plane saturation,
            and why conventional mitigations are ineffective.
          </p>
        </div>

        <section id="what-is-sdn" aria-labelledby="sdn-h">
          <h2 id="sdn-h">What is Software-Defined Networking?</h2>
          <p>
            Software-Defined Networking (SDN) decouples the <strong>control plane</strong>{" "}
            (decisions about where traffic goes) from the <strong>data plane</strong>{" "}
            (physical forwarding of traffic). A centralized software <strong>controller</strong>{" "}
            programs network switches using OpenFlow, enabling dynamic, programmable network
            management without per-device configuration.
          </p>
        </section>

        <section id="multi-domain" aria-labelledby="md-h">
          <h2 id="md-h">Multi-Domain Architecture</h2>
          <p>
            As networks scale, a single centralized controller becomes a bottleneck and a
            single point of failure. The standard solution is a{" "}
            <strong>multi-controller, multi-domain architecture</strong> — the network is
            partitioned into administrative domains, each managed by an independent controller.
          </p>
          <p>
            Controllers maintain a consistent global view by exchanging topology and
            link-state information via an <strong>East-West (E-W) protocol</strong>.
            In this project, three Ryu controller instances manage Domains A, B, and C,
            communicating over a custom REST-based E-W API.
          </p>
        </section>

        <section id="vulnerability" aria-labelledby="vuln-h">
          <h2 id="vuln-h">The Vulnerability: PacketIn Saturation</h2>
          <p>
            When an OpenFlow switch receives a packet with no matching flow-table rule
            (a "table-miss"), it sends a <strong>PacketIn</strong> message to its controller.
            Ryu processes these in a <strong>single-threaded event loop</strong>.
          </p>
          <p>
            An attacker generating packets with <strong>randomized source MAC and IP
            addresses</strong> ensures every packet triggers a table-miss. At rates up to
            5,000 pkt/s, the controller&apos;s event queue fills faster than it can be drained:
          </p>
          <ul>
            <li>The event queue grows unboundedly</li>
            <li>Legitimate control messages queue behind attack PacketIn messages</li>
            <li>Controller CPU reaches saturation trying to process the flood</li>
            <li>Domain A latency spikes from ~13.8 ms to <strong>&gt;1,350 ms</strong> (preliminary testbed result)</li>
            <li>East-West synchronization breaks down — the global topology registry diverges</li>
          </ul>
        </section>

        <section id="why-fails" aria-labelledby="wf-h">
          <h2 id="wf-h">Why Standard Mitigations Fail</h2>
          <div className="callout danger">
            <div className="callout-title">del-flows is Counterproductive</div>
            <p>
              The standard response — flushing the flow table (<code>del-flows</code>) —
              makes the situation <em>worse</em>. Deleting existing rules causes all current
              legitimate flows to re-trigger table-miss events, generating even more PacketIn
              messages and deepening the queue backlog.
            </p>
          </div>
          <p>
            The root cause is the controller&apos;s <strong>internal event queue</strong> — not
            the flow table. The event queue is an internal process data structure that cannot
            be externally cleared without terminating the process. This is why the circuit
            breaker uses <code>SIGKILL</code> rather than any OpenFlow-level intervention.
          </p>
          <p>
            A graceful shutdown (<code>SIGTERM</code>) is also ineffective in this state:
            handling the signal requires the event loop to run, which is blocked processing
            attack messages.
          </p>
        </section>

        <section id="ew-attacks" aria-labelledby="ew-h">
          <h2 id="ew-h">East-West Flooding and Topology Poisoning</h2>
          <p>Two additional attack surfaces exist in multi-domain SDN:</p>
          <ul>
            <li>
              <strong>East-West REST Flood</strong> — A rogue peer overwhelms the{" "}
              <code>/update</code> endpoint with high-frequency HTTP POSTs, disrupting
              legitimate E-W synchronization. Does <em>not</em> saturate controller CPU.
            </li>
            <li>
              <strong>Topology Poisoning</strong> — Crafted JSON payloads inject false
              topology or utilization data into the global registry, causing the TE engine
              to make incorrect routing decisions. Does <em>not</em> saturate controller CPU.
            </li>
          </ul>
          <p>
            These attacks degrade performance but are qualitatively different from PacketIn
            saturation — neither elevates controller CPU past the 70% threshold. The dual-signal
            circuit breaker is designed to distinguish these attack types.
          </p>
        </section>

        <section id="summary" aria-labelledby="sum-h">
          <h2 id="sum-h">Attack Comparison Summary</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Attack Type</th><th>Primary Effect</th><th>Controller CPU</th><th>CB Trigger</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>PacketIn Flood</td>
                  <td>Event-queue saturation, latency &gt;1,350 ms</td>
                  <td style={{ color: "var(--coral)" }}>Critical (&gt;70%)</td>
                  <td style={{ color: "var(--mint)" }}>Yes ✓</td>
                </tr>
                <tr>
                  <td>E-W REST Flood</td>
                  <td>Synchronization disruption</td>
                  <td>Low–Moderate</td>
                  <td style={{ color: "var(--text-muted)" }}>No ✗</td>
                </tr>
                <tr>
                  <td>Topology Poisoning</td>
                  <td>Incorrect routing decisions</td>
                  <td>Low</td>
                  <td style={{ color: "var(--text-muted)" }}>No ✗</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <Link href="/docs/objectives" className="btn btn-primary">Objectives & Scope →</Link>
            <Link href="/methodology" className="btn btn-secondary">Methodology →</Link>
          </div>
        </section>
      </article>
    </div>
  );
}
