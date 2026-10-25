import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Novel Contributions",
  description: "Event-queue root cause, out-of-band recovery, dual-signal detection, hardware throttling, cross-domain congestion-aware TE.",
};

export default function ContributionsPage() {
  return (
    <div className="docs-layout">
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {[
            { href: "#root-cause", label: "Event-Queue Root Cause" },
            { href: "#out-of-band", label: "Out-of-Band Recovery" },
            { href: "#dual-signal", label: "Dual-Signal Detection" },
            { href: "#hardware-throttle", label: "Hardware Throttling" },
            { href: "#cross-domain-te", label: "Cross-Domain TE" },
            { href: "#summary", label: "Summary" },
          ].map((item) => (
            <li key={item.href} className="sidebar-nav-item">
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>
      </aside>

      <article className="docs-article" aria-labelledby="cont-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="cont-title">Novel Contributions</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Principal technical contributions of this project. Claims are attributed to
            the project&apos;s own reported work. No &ldquo;first ever&rdquo; claims are made
            beyond what the presentation supports.
          </p>
        </div>

        <section id="root-cause" aria-labelledby="rc-h">
          <h2 id="rc-h">1. Event-Queue Saturation as Root Cause</h2>
          <p>
            The project explicitly identifies the SDN controller&apos;s{" "}
            <strong>internal event queue</strong> as the fundamental vulnerability exploited
            by PacketIn floods — distinct from CPU overload, memory exhaustion, or network
            congestion.
          </p>
          <p>
            This distinction is critical: it explains why conventional mitigations
            (flow-table flushes, switch-level rate-limiting, graceful shutdown) all fail.
            The event queue is an internal controller data structure that cannot be externally
            cleared without terminating the process.
          </p>
          <div className="callout success">
            <div className="callout-title">Empirical Validation (Preliminary)</div>
            <p>
              Preliminary testbed experiments provide empirical demonstration that a targeted
              SIGKILL is both necessary and sufficient to clear the poisoned state and restore
              normal latency.
            </p>
          </div>
        </section>

        <section id="out-of-band" aria-labelledby="oob-h">
          <h2 id="oob-h">2. Out-of-Band Controller Recovery</h2>
          <p>
            The circuit breaker daemon operates entirely <strong>outside the SDN control
            plane</strong>. It uses OS-level process management (<code>SIGKILL</code>,{" "}
            <code>subprocess.Popen</code>) and direct OVS switch commands (<code>ovs-ofctl</code>)
            rather than OpenFlow or E-W API calls.
          </p>
          <p>
            This architectural choice makes the defense mechanism immune to the attack
            condition it is designed to address. A defense that relies on the failing
            controller&apos;s API would fail precisely when controller is unresponsive.
          </p>
        </section>

        <section id="dual-signal" aria-labelledby="ds-h">
          <h2 id="ds-h">3. Dual-Signal Detection</h2>
          <p>
            The detection trigger requires <strong>simultaneous elevation</strong> of two
            independent signals — edge switch PacketIn rate (&gt;1,500 pkt/s) and controller
            CPU (&gt;70%) — sustained for three consecutive one-second samples.
          </p>
          <p>
            In limited preliminary testing, this design correctly distinguished PacketIn
            saturation from data-plane link congestion, East-West REST floods, and topology
            poisoning — none of which simultaneously raise both signals past threshold.
          </p>
          <div className="callout warning">
            <div className="callout-title">Scope of Evidence</div>
            <p>
              The false-positive characterization comes from a small number of trials.
              This is a preliminary observation, not a statistical guarantee.
            </p>
          </div>
        </section>

        <section id="hardware-throttle" aria-labelledby="ht-h">
          <h2 id="ht-h">4. Hardware-Level Flood Throttling Before Reconnection</h2>
          <p>
            The &ldquo;Prevention&rdquo; stage installs an OpenFlow Meter
            (<code>band=type=drop, rate=100 pkt/s</code>) at the ingress switch port{" "}
            <em>before</em> the restarted controller is allowed to reconnect, using an
            out-of-band <code>ovs-ofctl</code> command that does not require the controller
            to be running.
          </p>
          <p>
            Without this stage, preliminary experiments found that the freshly restarted
            controller was immediately re-saturated by the ongoing flood, causing a continuous
            kill/restart loop (controller flapping). The prevention stage breaks this cycle.
          </p>
        </section>

        <section id="cross-domain-te" aria-labelledby="te-h">
          <h2 id="te-h">5. Congestion-Aware Multi-Domain Routing</h2>
          <p>
            The TE engine implements a Dijkstra path selector with congestion-aware edge
            weights spanning <strong>all three domains</strong> via the shared global
            topology registry.
          </p>
          <ul>
            <li>Edge weights: <code>w(e) = 1 / (1 − u(e))</code> for uncongested links — smooth congestion avoidance</li>
            <li>Congested links (<code>u(e) ≥ 0.70</code>) are penalized out of selection</li>
            <li>Boundary port statistics explicitly exchanged over E-W for cross-domain visibility</li>
            <li>Synchronization barrier (<code>OFPT_BARRIER_REQUEST</code>) ensures atomic flow installation</li>
          </ul>
          <p>
            This allows the TE engine to route around congestion across domain boundaries,
            not just within a single controller&apos;s domain.
          </p>
        </section>

        <section id="summary" aria-labelledby="sum-h">
          <h2 id="sum-h">Summary</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Contribution</th><th>Key Property</th></tr></thead>
              <tbody>
                <tr><td>Event-queue root cause identification</td><td>Explains why standard mitigations fail</td></tr>
                <tr><td>Out-of-band controller recovery</td><td>Immune to the attack condition it addresses</td></tr>
                <tr><td>Dual-signal detection</td><td>Reduces false positives in preliminary testing</td></tr>
                <tr><td>Hardware pre-reconnect throttling</td><td>Prevents controller flapping</td></tr>
                <tr><td>Cross-domain congestion-aware TE</td><td>Global congestion visibility via E-W protocol</td></tr>
              </tbody>
            </table>
          </div>
          <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <Link href="/results" className="btn btn-primary">View Results →</Link>
            <Link href="/docs/future-work" className="btn btn-secondary">Future Work →</Link>
          </div>
        </section>
      </article>
    </div>
  );
}
