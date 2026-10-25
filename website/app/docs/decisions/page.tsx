import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Technical Decisions",
  description: "Why congestion-aware Dijkstra, edge-weight math, dual-signal decision rule, parameter trade-offs and limitations.",
};

export default function DecisionsPage() {
  return (
    <div className="docs-layout">
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {[
            { href: "#dijkstra", label: "Why Dijkstra" },
            { href: "#math", label: "Edge Weight Math" },
            { href: "#dual-signal", label: "Dual-Signal Rule" },
            { href: "#params", label: "Parameter Rationale" },
            { href: "#sigkill", label: "SIGKILL vs SIGTERM" },
            { href: "#edge-cases", label: "Edge Cases" },
          ].map((item) => (
            <li key={item.href} className="sidebar-nav-item">
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>
      </aside>

      <article className="docs-article" aria-labelledby="dec-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="dec-title">Technical Decisions</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Design rationale, mathematical formulations, parameter trade-offs, and
            known limitations of the implemented system.
          </p>
        </div>

        <section id="dijkstra" aria-labelledby="dij-h">
          <h2 id="dij-h">Why Congestion-Aware Dijkstra?</h2>
          <p>Standard shortest-path routing minimizes hop count — it ignores link load. The project required a path selector that:</p>
          <ol>
            <li>Works on arbitrary graph topologies</li>
            <li>Incorporates real-time link utilization as a cost signal</li>
            <li>Is computationally feasible for a 9-switch topology (and reasonably scalable)</li>
            <li>Produces deterministic, reproducible results</li>
          </ol>
          <p>
            Dijkstra satisfies all four requirements with a straightforward modification:
            replace the hop-count edge weight with a congestion-penalty function.
            More sophisticated approaches (MCMF, LP-based TE) are possible future extensions
            but add implementation complexity not warranted for an initial research prototype.
          </p>
        </section>

        <section id="math" aria-labelledby="math-h">
          <h2 id="math-h">Edge Weight Formulation</h2>
          <h3>Definitions</h3>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Meaning</th></tr></thead>
              <tbody>
                <tr><td>G = (V, E)</td><td>Global topology graph across all three domains</td></tr>
                <tr><td>u(e)</td><td>Current utilization of edge e, normalized 0–1</td></tr>
                <tr><td>T</td><td>Congestion threshold = 0.70 (70%)</td></tr>
                <tr><td>w(e)</td><td>Edge weight assigned to e in Dijkstra</td></tr>
                <tr><td>PENALTY</td><td>Large constant — effectively removes congested edge from selection</td></tr>
              </tbody>
            </table>
          </div>
          <h3>Formulation</h3>
          <pre>{`For u(e) < T  (link is uncongested):
         1
w(e) = ──────────
        1 − u(e)

For u(e) ≥ T  (link is congested):
w(e) = PENALTY`}</pre>
          <h3>Properties</h3>
          <ul>
            <li>At <code>u(e) = 0</code> (idle): <code>w(e) = 1</code> — minimum weight, freely selected</li>
            <li>As <code>u(e) → T</code>: <code>w(e) → ∞</code> — path becomes progressively avoided</li>
            <li>At <code>u(e) ≥ T</code>: PENALTY — link excluded unless no alternative exists</li>
            <li>Smooth monotonic increase — provides gradual load-balancing, not cliff-edge switching</li>
          </ul>
          <h3>Path Objective</h3>
          <pre>{`Path* = argmin  Σ w(e)
              e ∈ path P`}</pre>
        </section>

        <section id="dual-signal" aria-labelledby="ds-h">
          <h2 id="ds-h">Dual-Signal Decision Rule</h2>
          <p>A single detection signal is prone to false positives:</p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Single Signal</th><th>Limitation</th></tr></thead>
              <tbody>
                <tr><td>PacketIn rate only</td><td>Legitimate ARP floods, scanning, or broadcasts can spike without saturating the controller</td></tr>
                <tr><td>CPU only</td><td>Background OS jobs, GC pauses, or unrelated Ryu modules can spike CPU</td></tr>
              </tbody>
            </table>
          </div>
          <p>
            The <strong>conjunction</strong> of both signals — PacketIn rate &gt;1,500 pkt/s
            AND CPU &gt;70% — is specific to the attack scenario: an active flood that has
            already caused controller saturation. In preliminary testing, this combination
            was not triggered by E-W or topology attacks.
          </p>
          <p>
            The <strong>3-consecutive-second window</strong> eliminates single-sample transients.
            The trade-off: ~3 s of confirmed saturation before mitigation begins, which
            is the primary driver of the ~3 s reported detection time.
          </p>
        </section>

        <section id="params" aria-labelledby="par-h">
          <h2 id="par-h">Parameter Rationale and Trade-Offs</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Parameter</th><th>Value</th><th>Too Low</th><th>Too High</th><th>Rationale</th></tr></thead>
              <tbody>
                <tr>
                  <td>PacketIn threshold</td>
                  <td>1,500 pkt/s</td>
                  <td>False positives from burst traffic</td>
                  <td>Delayed detection; more queue backlog</td>
                  <td>Provides clear separation from normal traffic at tested attack profile</td>
                </tr>
                <tr>
                  <td>CPU threshold</td>
                  <td>70%</td>
                  <td>False positives from background load</td>
                  <td>Detection only at near-total saturation</td>
                  <td>Matches TE congestion threshold; standard for operational alerting</td>
                </tr>
                <tr>
                  <td>Confirmation window</td>
                  <td>3 s</td>
                  <td>False positives from transient spikes</td>
                  <td>Longer saturation before mitigation</td>
                  <td>Eliminates single-sample transients; 3 s is the measured detection cost</td>
                </tr>
                <tr>
                  <td>Meter rate limit</td>
                  <td>100 pkt/s</td>
                  <td>Too restrictive on legitimate traffic</td>
                  <td>Attacker throughput too high; re-saturation possible</td>
                  <td>50× reduction from 5,000 pkt/s max; allows controller startup without re-saturation</td>
                </tr>
                <tr>
                  <td>Meter duration</td>
                  <td>60 s</td>
                  <td>Meter expires before controller fully reconnects</td>
                  <td>Rate-limits legitimate traffic unnecessarily long</td>
                  <td>Covers the ~16.7 s recovery window with comfortable margin</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section id="sigkill" aria-labelledby="sk-h">
          <h2 id="sk-h">SIGKILL vs. SIGTERM</h2>
          <div className="callout danger">
            <div className="callout-title">Why Not Graceful Shutdown?</div>
            <p>
              <code>SIGTERM</code> requires the target process to <em>handle</em> the signal —
              which requires the event loop to run. When the event queue is full,
              the event loop is blocked processing attack PacketIn messages.
              <code>SIGTERM</code> is therefore effectively ignored in a saturation state.
            </p>
          </div>
          <p>
            <code>SIGKILL</code> bypasses the event loop entirely. The OS terminates the
            process immediately, freeing all memory including the poisoned event queue.
          </p>
          <p>
            <strong>Risk:</strong> In-flight state is lost (active sessions, pending FlowMods).
            This is acceptable because that state is already corrupted; the goal is to clear
            the poison and start fresh with a clean controller process.
          </p>
        </section>

        <section id="edge-cases" aria-labelledby="ec-h">
          <h2 id="ec-h">Edge Cases and Known Limitations</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Scenario</th><th>Current Behavior</th><th>Limitation</th></tr></thead>
              <tbody>
                <tr><td>Distributed flood (multiple source hosts)</td><td>Each host below threshold individually</td><td>Combined rate may not be detected</td></tr>
                <tr><td>Slow-rate attack (&quot;Low and Slow&quot;)</td><td>Stays below 1,500 pkt/s; undetected</td><td>Proposed ML extension (future work)</td></tr>
                <tr><td>Multi-domain simultaneous attack</td><td>Domain A circuit breaker only</td><td>Single-domain protection</td></tr>
                <tr><td>Non-attack controller crash</td><td>May trigger if CPU also elevated</td><td>Could misclassify hardware faults</td></tr>
                <tr><td>Recovery window &gt; 60 s</td><td>Meter expires; re-saturation possible</td><td>Fixed meter duration not adaptive</td></tr>
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
