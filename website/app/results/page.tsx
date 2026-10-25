import type { Metadata } from "next";
import Link from "next/link";
import { ScrollReveal } from "@/components/ScrollReveal";

export const metadata: Metadata = {
  title: "Results & Evaluation",
  description:
    "Preliminary testbed results: ~3 s detection, ~16.7 s mitigation, 14.02 ms post-recovery latency. Evidence caveats included.",
};

const PHASE4 = [
  { metric: "Congestion trigger threshold", value: "70% utilization", note: "> 700 Mbps on 1,000 Mbps links" },
  { metric: "Trigger time (approx.)", value: "~15 s mark", note: "After iperf3 background flow saturated path" },
  { metric: "Rerouted path", value: "s1–s4–s7–s8", note: "Alternate low-utilization route" },
  { metric: "Post-reroute latency", value: "~15 ms", note: "Similar to baseline" },
];

const PHASE5 = [
  { metric: "Attack type", value: "PacketIn Flood", note: "5,000 pkt/s at max rate" },
  { metric: "Pre-attack latency (baseline)", value: "~13.8 ms", note: "Domain A, no attack" },
  { metric: "Peak latency (undefended)", value: "> 1,350 ms", note: "~100× degradation" },
  { metric: "E-W synchronization", value: "Broke down", note: "Controller too saturated to process E-W" },
  { metric: "del-flows mitigation", value: "Completely ineffective", note: "Queue poisoning, not flow-table problem" },
];

const PHASE6 = [
  { metric: "Detection time", value: "~3.0 s", accent: "var(--cyan)" },
  { metric: "Controller restart time", value: "~1–2 s", accent: "var(--amber)" },
  { metric: "Health verification window", value: "~13 s", accent: "var(--blue)" },
  { metric: "Total mitigation time", value: "~16.7 s", accent: "var(--mint)" },
  { metric: "Post-mitigation latency", value: "14.02 ms", accent: "var(--mint)" },
  { metric: "Baseline latency", value: "~13.8 ms", accent: "var(--text-secondary)" },
];

const FALSE_POS = [
  { attack: "PacketIn Flood", cpuElevated: true, rateElevated: true, cbTriggered: true, note: "Intended trigger" },
  { attack: "E-W REST Flood", cpuElevated: false, rateElevated: false, cbTriggered: false, note: "Correct — CB ignores" },
  { attack: "Topology Poisoning", cpuElevated: false, rateElevated: false, cbTriggered: false, note: "Correct — CB ignores" },
];

function Tick({ yes }: { yes: boolean }) {
  return (
    <span
      style={{ color: yes ? "var(--mint)" : "var(--text-muted)", fontWeight: 700, fontSize: "1rem" }}
      aria-label={yes ? "Yes" : "No"}
    >
      {yes ? "✓" : "✗"}
    </span>
  );
}

export default function ResultsPage() {
  return (
    <div className="docs-layout">
      {/* Sidebar */}
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {[
            { href: "#caveat", label: "Evidence Caveat" },
            { href: "#scenarios", label: "Experimental Scenarios" },
            { href: "#phase4", label: "Phase 4 — TE" },
            { href: "#phase5", label: "Phase 5 — Undefended" },
            { href: "#phase6", label: "Phase 6 — Defended" },
            { href: "#false-pos", label: "False Positives" },
            { href: "#what-results-show", label: "Interpretation" },
          ].map((item) => (
            <li key={item.href} className="sidebar-nav-item">
              <a href={item.href}>{item.label}</a>
            </li>
          ))}
        </ul>
      </aside>

      {/* Main article */}
      <article className="docs-article" aria-labelledby="res-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="res-title">Results &amp; Evaluation</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Baseline, undefended, defended, and traffic-engineering comparisons from the
            Mininet testbed. All figures are preliminary.
          </p>
        </div>

        {/* Caveat */}
        <section id="caveat">
          <div className="callout warning">
            <div className="callout-title">Important: Preliminary Testbed Evidence Only</div>
            <p>
              All measurements on this page are from a <strong>single-instance Mininet software testbed</strong>{" "}
              running specific attack profiles and a 9-switch topology. They represent preliminary
              experimental observations. Broader evaluation — with repeated trials, statistical
              confidence intervals, varied topologies, varied traffic profiles, and hardware
              validation — is required before these findings can be generalized.
            </p>
          </div>
        </section>

        {/* Scenarios */}
        <section id="scenarios" aria-labelledby="sc-h">
          <h2 id="sc-h">Experimental Scenarios</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Phase</th><th>Scenario</th><th>Description</th></tr>
              </thead>
              <tbody>
                <tr><td>4</td><td>TE evaluation</td><td>Background iperf3 congestion + TE rerouting active, no attack</td></tr>
                <tr><td>5</td><td>Undefended</td><td>PacketIn flood at up to 5,000 pkt/s, no circuit breaker</td></tr>
                <tr><td>6</td><td>Defended</td><td>PacketIn flood at up to 5,000 pkt/s, circuit breaker enabled</td></tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* Phase 4 */}
        <section id="phase4" aria-labelledby="p4-h">
          <h2 id="p4-h">Phase 4 — Traffic Engineering <span className="badge warning" style={{ fontSize: "0.65rem", verticalAlign: "middle" }}>Preliminary</span></h2>
          <p>
            A continuous UDP flood from <code>h4</code> to <code>h9</code> pinned the
            A–C diagonal (s1–s2–s3–s5–s8–s9) above 70% utilization. A new test flow
            from <code>h1</code> to <code>h11</code> was then established.
          </p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Metric</th><th>Observed Value</th><th>Note</th></tr></thead>
              <tbody>
                {PHASE4.map((r) => (
                  <tr key={r.metric}><td>{r.metric}</td><td>{r.value}</td><td>{r.note}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Source: Figure 1 — TE link utilization chart (
            <code>results/figures/fig1_te_utilization.png</code> in the repository).
          </p>
        </section>

        {/* Phase 5 */}
        <section id="phase5" aria-labelledby="p5-h">
          <h2 id="p5-h">Phase 5 — Undefended System <span className="badge warning" style={{ fontSize: "0.65rem", verticalAlign: "middle" }}>Preliminary</span></h2>

          <div className="callout danger">
            <div className="callout-title">Attack Profile</div>
            <p>
              PacketIn flood from h1, targeting Domain A controller (Ryu A, port 6633).
              Ramp: 500 pkt/s start → +500 pkt/s every 10 s → 5,000 pkt/s max, sustained 20 s.
              Generated by Scapy with randomized source MAC/IP (AF_PACKET raw sockets).
            </p>
          </div>

          <div className="table-wrap">
            <table>
              <thead><tr><th>Metric</th><th>Observed Value</th><th>Note</th></tr></thead>
              <tbody>
                {PHASE5.map((r) => (
                  <tr key={r.metric}><td>{r.metric}</td><td>{r.value}</td><td>{r.note}</td></tr>
                ))}
              </tbody>
            </table>
          </div>

          <ScrollReveal>
            <div className="card" style={{ marginTop: "1.5rem", borderColor: "rgba(255,100,124,0.3)" }}>
              <h3 style={{ color: "var(--coral)", fontSize: "1rem", marginBottom: "0.75rem" }}>Why del-flows Fails</h3>
              <p style={{ fontSize: "0.9rem" }}>
                Flushing the flow table (<code>del-flows</code>) causes <em>all existing legitimate flows</em> to
                re-trigger table-miss → PacketIn events. This makes the queue problem worse, not better.
                The fix requires killing the controller process to clear the queue — which is exactly
                what the circuit breaker does.
              </p>
            </div>
          </ScrollReveal>
        </section>

        {/* Phase 6 */}
        <section id="phase6" aria-labelledby="p6-h">
          <h2 id="p6-h">Phase 6 — Defended System <span className="badge done" style={{ fontSize: "0.65rem", verticalAlign: "middle" }}>Circuit Breaker Active</span></h2>

          <ScrollReveal>
            <div className="metric-grid" style={{ marginBottom: "1.5rem" }}>
              {PHASE6.slice(0, 4).map((m) => (
                <div key={m.metric} className="metric-card cyan" style={{ borderTopColor: m.accent }}>
                  <div className="metric-label">{m.metric}</div>
                  <div className="metric-value" style={{ color: m.accent }}>{m.value}</div>
                  <div className="metric-sub">preliminary testbed result</div>
                </div>
              ))}
            </div>
          </ScrollReveal>

          <div className="table-wrap">
            <table>
              <thead><tr><th>Metric</th><th>Value</th><th>Context</th></tr></thead>
              <tbody>
                {PHASE6.map((r) => (
                  <tr key={r.metric}>
                    <td>{r.metric}</td>
                    <td style={{ color: r.accent, fontFamily: "var(--font-jetbrains-mono, monospace)", fontSize: "0.9rem" }}>{r.value}</td>
                    <td>preliminary testbed result</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="callout success" style={{ marginTop: "1rem" }}>
            <div className="callout-title">Recovery Quality</div>
            <p>
              Post-mitigation latency of <strong>14.02 ms</strong> vs. a pre-attack baseline of
              <strong> ~13.8 ms</strong> — a difference of approximately <strong>0.2 ms</strong>.
              The circuit breaker restored essentially normal operation in the testbed run.
            </p>
          </div>

          <p style={{ marginTop: "1rem" }}>
            Source: Figure 2 — Attack latency comparison chart and Figure 3 — detection accuracy
            (repository: <code>results/figures/</code>).
          </p>
        </section>

        {/* False Positives */}
        <section id="false-pos" aria-labelledby="fp-h">
          <h2 id="fp-h">False-Positive Characterization <span className="badge warning" style={{ fontSize: "0.65rem", verticalAlign: "middle" }}>Limited Trials</span></h2>
          <p>
            The circuit breaker was tested against the other two attack types to assess
            specificity. <strong>This is a preliminary observation from very limited
            trials — not a statistical guarantee of zero false positives in production.</strong>
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Attack Type</th>
                  <th>CPU Elevated?</th>
                  <th>PacketIn Elevated?</th>
                  <th>CB Triggered?</th>
                  <th>Assessment</th>
                </tr>
              </thead>
              <tbody>
                {FALSE_POS.map((r) => (
                  <tr key={r.attack}>
                    <td>{r.attack}</td>
                    <td><Tick yes={r.cpuElevated} /></td>
                    <td><Tick yes={r.rateElevated} /></td>
                    <td><Tick yes={r.cbTriggered} /></td>
                    <td>{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Interpretation */}
        <section id="what-results-show" aria-labelledby="interp-h">
          <h2 id="interp-h">What the Results Do and Do Not Establish</h2>

          <h3 style={{ color: "var(--mint)" }}>What the results suggest</h3>
          <ul>
            <li>The dual-signal detection approach can distinguish PacketIn saturation from data-plane attacks in this specific testbed configuration.</li>
            <li>The kill + restart + rate-limit pipeline can recover normal operation in approximately 17 seconds under the tested attack profile.</li>
            <li>Congestion-aware TE can redirect flows away from congested links at the 70% threshold.</li>
          </ul>

          <h3 style={{ color: "var(--coral)", marginTop: "1.5rem" }}>What the results do NOT establish</h3>
          <ul>
            <li>Performance under different attack rates, attacker positions, or ramp profiles</li>
            <li>Behavior with more than 3 domains or more than 9 switches</li>
            <li>False-positive rates across many benign trials (the current number of benign trials is very small)</li>
            <li>Statistical confidence intervals on any of the reported timings</li>
            <li>Behavior on physical hardware vs. Mininet emulation</li>
            <li>Generalizability beyond the specific Ryu + OVS + Linux environment tested</li>
          </ul>

          <h3 style={{ color: "var(--amber)", marginTop: "1.5rem" }}>Future validation requirements</h3>
          <ul>
            <li>Repeated experimental trials with mean, standard deviation, and confidence intervals</li>
            <li>Testing across varied topologies, switch counts, and host configurations</li>
            <li>Physical hardware validation</li>
            <li>Testing with different attack profiles (slow-rate, multi-vector, distributed sources)</li>
            <li>Benign trial characterization to establish false-positive base rates</li>
          </ul>

          <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <Link href="/docs" className="btn btn-primary">Full Documentation →</Link>
            <Link href="/architecture" className="btn btn-secondary">Architecture →</Link>
          </div>
        </section>
      </article>
    </div>
  );
}
