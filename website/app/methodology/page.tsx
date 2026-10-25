import type { Metadata } from "next";
import Link from "next/link";
import { ScrollReveal } from "@/components/ScrollReveal";

export const metadata: Metadata = {
  title: "Methodology",
  description:
    "Mininet/Ryu testbed, East-West REST protocol, congestion-aware Dijkstra routing, attack suite, and circuit breaker stages.",
};

const ATTACKS = [
  {
    name: "PacketIn Flood",
    type: "North-South",
    color: "var(--coral)",
    target: "Domain A controller event queue",
    mechanism: "Randomized source MAC/IP forces 100% table-miss → PacketIn to controller",
    effect: "Unbounded event-queue saturation, CPU >70%, latency >1,350 ms",
    cbTriggered: true,
  },
  {
    name: "East-West REST Flood",
    type: "East-West",
    color: "var(--amber)",
    target: "/update REST endpoint",
    mechanism: "High-frequency POST requests from a simulated rogue peer controller",
    effect: "E-W synchronization disruption, topology divergence",
    cbTriggered: false,
  },
  {
    name: "Topology Poisoning",
    type: "East-West",
    color: "var(--blue)",
    target: "/update REST endpoint",
    mechanism: "Crafted JSON payloads inject false topology or utilization data",
    effect: "TE engine makes incorrect routing decisions, possible traffic black-holes",
    cbTriggered: false,
  },
];

const DETECTION = [
  { signal: "PacketIn rate", source: "Edge switch s1 PortStats", threshold: "> 1,500 pkt/s", note: "Datapath signal" },
  { signal: "Controller CPU", source: "psutil on ryu-manager A", threshold: "> 70%", note: "Compute signal" },
  { signal: "Duration", source: "Daemon counter", threshold: "3 consecutive seconds", note: "Both signals elevated" },
];

export default function MethodologyPage() {
  return (
    <div className="docs-layout">
      {/* Sidebar */}
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {[
            { href: "#testbed", label: "Testbed Environment" },
            { href: "#startup", label: "Startup Sequence" },
            { href: "#ew-protocol", label: "East-West Protocol" },
            { href: "#te", label: "Traffic Engineering" },
            { href: "#attacks", label: "Attack Suite" },
            { href: "#detection", label: "Detection Parameters" },
            { href: "#mitigation", label: "Mitigation & Prevention" },
          ].map((item) => (
            <li key={item.href} className="sidebar-nav-item">
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>
      </aside>

      {/* Main article */}
      <article className="docs-article" aria-labelledby="meth-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="meth-title">Methodology</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Mininet/Ryu testbed setup, East-West protocol, congestion-aware routing,
            attack characterization, and circuit breaker detection and mitigation design.
          </p>
        </div>

        {/* Testbed */}
        <section id="testbed" aria-labelledby="tb-h">
          <h2 id="tb-h">Testbed Environment</h2>
          <p>
            All experiments run on a single Linux machine using <strong>Mininet</strong> (Python API)
            to emulate the full multi-domain network in software. Each switch is an
            Open vSwitch (OVS) instance running <strong>OpenFlow 1.3</strong>. Three separate
            <code>ryu-manager</code> processes, each running <code>ew_controller.py</code>,
            manage their respective domains independently.
          </p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Component</th><th>Technology</th><th>Version / Detail</th></tr></thead>
              <tbody>
                <tr><td>Network emulator</td><td>Mininet (Python API)</td><td>Linux host</td></tr>
                <tr><td>SDN framework</td><td>Ryu (ryu-manager)</td><td>3 independent instances</td></tr>
                <tr><td>Protocol</td><td>OpenFlow</td><td>Version 1.3</td></tr>
                <tr><td>Switches</td><td>Open vSwitch (OVS)</td><td>9 instances</td></tr>
                <tr><td>Backbone bandwidth</td><td>TCLink</td><td>1,000 Mbps</td></tr>
                <tr><td>Edge bandwidth</td><td>TCLink</td><td>100 Mbps</td></tr>
                <tr><td>Traffic generator</td><td>iperf3</td><td>Background TE flows</td></tr>
                <tr><td>Attack generator</td><td>Scapy (AF_PACKET)</td><td>Raw socket floods</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* Startup */}
        <section id="startup" aria-labelledby="startup-h">
          <h2 id="startup-h">Startup Sequence</h2>
          <p>
            The startup order was found to be critical for stability. OVS handshake and
            STP timing issues caused frequent controller disconnections during early
            development. The resolution:
          </p>
          <ol style={{ paddingLeft: "1.5rem", color: "var(--text-secondary)" }}>
            <li style={{ marginBottom: "0.5rem" }}>Enable RSTP globally across all OVS switches — prevents STP reconvergence during startup</li>
            <li style={{ marginBottom: "0.5rem" }}>Wait for the network topology to stabilize</li>
            <li style={{ marginBottom: "0.5rem" }}>Assign each controller to its domain&apos;s switches</li>
            <li style={{ marginBottom: "0.5rem" }}>Start the East-West REST APIs</li>
            <li style={{ marginBottom: "0.5rem" }}>Allow topology discovery to complete before running experiments</li>
          </ol>
        </section>

        {/* E-W Protocol */}
        <section id="ew-protocol" aria-labelledby="ewp-h">
          <h2 id="ewp-h">East-West Protocol</h2>
          <p>
            Controllers poll each other&apos;s REST endpoints at regular intervals and merge
            the results into the shared <code>global_topology</code> registry.
          </p>
          <p>
            A key challenge was that controllers initially only tracked PortStats for their
            own switches — making boundary link utilization invisible to the TE engine.
            The resolution: each controller explicitly exchanges <strong>boundary port
            statistics</strong> over E-W, and the TE <code>compute_path</code> function
            consumes pre-computed utilization rates across all domains.
          </p>
          <div className="callout warning">
            <div className="callout-title">Security Note</div>
            <p>
              The E-W protocol has no authentication. Any process on the network can send
              crafted payloads to the <code>/update</code> endpoint — the mechanism of the
              Topology Poisoning attack. Authenticated E-W is planned future work.
            </p>
          </div>
        </section>

        {/* Traffic Engineering */}
        <section id="te" aria-labelledby="te-h">
          <h2 id="te-h">Congestion-Aware Traffic Engineering</h2>
          <p>
            The TE engine uses a modified Dijkstra algorithm on the global topology graph.
            Rather than minimizing hop count, it minimizes a <strong>congestion-aware edge
            weight</strong>:
          </p>
          <div className="diagram-frame" style={{ fontFamily: "var(--font-jetbrains-mono, monospace)", fontSize: "0.9rem" }}>
            <p style={{ color: "var(--text-secondary)", marginBottom: "0.75rem", fontSize: "0.8rem", fontFamily: "var(--font-inter)" }}>Edge weight formulation:</p>
            <pre style={{ margin: 0, background: "transparent", border: "none", padding: 0 }}>
{`For u(e) < T (uncongested):
         1
w(e) = ──────────
        1 − u(e)

For u(e) ≥ T (congested):
w(e) = PENALTY  (effectively ∞)`}
            </pre>
            <div style={{ marginTop: "1rem", fontSize: "0.8rem", color: "var(--text-muted)", fontFamily: "var(--font-inter)" }}>
              Where: u(e) = link utilization [0–1], T = 0.70 (70% threshold), PENALTY = large constant
            </div>
          </div>
          <p>
            This formulation smoothly penalizes high-utilization links and fully excludes
            congested links from path selection. When no uncongested path exists, the
            least-penalized path is used.
          </p>
          <h3>Flow Installation</h3>
          <p>
            New cross-domain paths are installed atomically: FlowMod messages are sent to
            each domain&apos;s switches, and an OpenFlow <code>OFPT_BARRIER_REQUEST</code>{" "}
            synchronization barrier confirms all FlowMods are processed before the path
            is considered active.
          </p>
        </section>

        {/* Attack Suite */}
        <section id="attacks" aria-labelledby="attacks-h">
          <h2 id="attacks-h">Attack Suite</h2>
          <p>
            Three attack modules were implemented to test the defense system. Scripts are
            in the <code>attacks/</code> directory of the{" "}
            <a href="https://github.com/a-anuj/resilent-multi-domain-sdn" target="_blank" rel="noopener noreferrer">repository</a>.
          </p>
          <div style={{ display: "grid", gap: "1rem" }}>
            {ATTACKS.map((a) => (
              <ScrollReveal key={a.name}>
                <div className="card">
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
                    <h3 style={{ fontSize: "1rem", color: a.color, margin: 0 }}>{a.name}</h3>
                    <div style={{ display: "flex", gap: "0.5rem" }}>
                      <span className="badge warning">{a.type}</span>
                      {a.cbTriggered
                        ? <span className="badge done">Triggers CB</span>
                        : <span className="badge future">CB ignores</span>
                      }
                    </div>
                  </div>
                  <div className="table-wrap" style={{ margin: 0, border: "none" }}>
                    <table>
                      <tbody>
                        <tr><td>Target</td><td>{a.target}</td></tr>
                        <tr><td>Mechanism</td><td>{a.mechanism}</td></tr>
                        <tr><td>Primary effect</td><td>{a.effect}</td></tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </ScrollReveal>
            ))}
          </div>
          <div className="callout info" style={{ marginTop: "1.5rem" }}>
            <div className="callout-title">Attack Ramp Profile (Phase 5)</div>
            <p>
              PacketIn flood: starts at <strong>500 pkt/s</strong>, steps up by{" "}
              <strong>+500 pkt/s</strong> every 10 seconds, reaches <strong>5,000 pkt/s</strong>,
              sustained for 20 seconds. Generated from h1 targeting Domain A (Ryu A, port 6633)
              using Scapy raw sockets with randomized source MAC/IP.
            </p>
          </div>
        </section>

        {/* Detection */}
        <section id="detection" aria-labelledby="det-h">
          <h2 id="det-h">Detection Parameters</h2>
          <p>
            The circuit breaker daemon polls two independent signals once per second.
            Triggering requires <strong>both</strong> to exceed threshold for <strong>three
            consecutive samples</strong> (3 seconds):
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Signal</th><th>Source</th><th>Threshold</th><th>Role</th></tr>
              </thead>
              <tbody>
                {DETECTION.map((d) => (
                  <tr key={d.signal}>
                    <td>{d.signal}</td>
                    <td><code>{d.source}</code></td>
                    <td><code>{d.threshold}</code></td>
                    <td>{d.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            The dual-signal requirement distinguishes PacketIn saturation (both signals high)
            from data-plane attacks (high bandwidth, low controller CPU) and background
            CPU load (high CPU, normal PacketIn rate).
          </p>
        </section>

        {/* Mitigation & Prevention */}
        <section id="mitigation" aria-labelledby="mit-h">
          <h2 id="mit-h">Mitigation and Prevention</h2>
          <h3>Kill and Restart</h3>
          <pre>{`# SIGKILL — bypasses the blocked event loop
os.kill(controller_pid, signal.SIGKILL)

# Immediately respawn
subprocess.Popen(CONTROLLER_A_START_CMD)`}</pre>
          <p>
            <code>SIGTERM</code> cannot be used because the event loop is blocked processing
            attack PacketIn messages — it would be effectively ignored. <code>SIGKILL</code>
            terminates the process at the OS level, instantly freeing all memory including
            the poisoned event queue.
          </p>

          <h3>Hardware Rate Limiting</h3>
          <pre>{`# Install Meter on s1 via ovs-ofctl (out-of-band)
ovs-ofctl add-meter s1 \\
  "meter=1,kbps,band=type=drop,rate=100"
# Expires after 60 seconds`}</pre>
          <p>
            This throttles the attacker to 100 pkt/s at the hardware level <em>before</em>{" "}
            the controller is allowed to reconnect — preventing the fresh controller from
            being immediately re-saturated (controller flapping).
          </p>

          <h3>Recovery Verification</h3>
          <pre>{`# Lightweight core endpoint — responds early in startup
GET http://localhost:8080/stats/switches`}</pre>
          <p>
            The original health-check used <code>/te_path</code>, which requires the full
            TE module to load and caused timeouts during recovery, generating false-failure
            reports. Switching to <code>/stats/switches</code> — a core OpenFlow endpoint —
            resolved this.
          </p>
          <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <Link href="/results" className="btn btn-primary">View Results →</Link>
            <Link href="/docs" className="btn btn-secondary">Full Documentation →</Link>
          </div>
        </section>
      </article>
    </div>
  );
}
