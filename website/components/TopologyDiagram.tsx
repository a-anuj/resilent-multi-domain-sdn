"use client";
import { useState } from "react";

type DomainId = "a" | "b" | "c" | null;

/* Colours intentionally restrained — one text colour, one accent, one dim */
const NODE   = { fill: "#0D1420", stroke: "#1B2840", text: "#C8D4E0" };
const LABEL  = "#4F8EF7";          /* accent for domain headers only */
const LINK   = "#253548";          /* all intra-domain links */
const INTER  = "#2D4060";          /* inter-domain boundary links */
const ALT    = "#334B68";          /* A-C alternate path (slightly brighter) */
const MUTED  = "#3A4F65";          /* legend / annotation text */

export function TopologyDiagram() {
  const [hovered, setHovered] = useState<DomainId>(null);

  const fade = (id: DomainId) =>
    hovered === null || hovered === id ? 1 : 0.28;

  return (
    <div
      className="diagram-frame"
      role="img"
      aria-label="9-switch 3-domain SDN topology diagram showing three domains each with three switches managed by independent Ryu controllers connected via inter-domain links."
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 860 440"
        style={{ maxWidth: "100%", height: "auto" }}
        aria-hidden="true"
        focusable="false"
      >
        {/* Background */}
        <rect width="860" height="440" fill="#090E18" />

        {/* Subtle grid */}
        <defs>
          <pattern id="topo-grid" width="44" height="44" patternUnits="userSpaceOnUse">
            <path d="M 44 0 L 0 0 0 44" fill="none" stroke="#111A2B" strokeWidth="1"/>
          </pattern>
        </defs>
        <rect width="860" height="440" fill="url(#topo-grid)" />

        {/* ══════════════════════════════
            DOMAIN A
        ══════════════════════════════ */}
        <g
          style={{ opacity: fade("a"), transition: "opacity 0.2s" }}
          onMouseEnter={() => setHovered("a")}
          onMouseLeave={() => setHovered(null)}
          role="group"
          aria-label="Domain A"
        >
          {/* Box */}
          <rect x="14" y="28" width="232" height="384" rx="6"
            fill="none" stroke="#1B2840" strokeWidth="1.5" />
          {/* Domain label */}
          <text x="130" y="20" fontFamily="JetBrains Mono, monospace" fontSize="9.5"
            fontWeight="600" fill={LABEL} textAnchor="middle" letterSpacing="3">
            DOMAIN A
          </text>

          {/* Controller badge */}
          <rect x="62" y="36" width="136" height="22" rx="3"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="130" y="51" fontFamily="JetBrains Mono, monospace" fontSize="8.5"
            fill="#3F5066" textAnchor="middle">
            Ryu-A · :6633 / :8080
          </text>

          {/* Controller → s1 dashed guide */}
          <line x1="130" y1="58" x2="92" y2="126" stroke="#151E2E"
            strokeWidth="1" strokeDasharray="4,4"/>

          {/* Hosts */}
          <rect x="24" y="132" width="24" height="13" rx="2"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="36" y="142" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">h1</text>

          <rect x="24" y="150" width="24" height="13" rx="2"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="36" y="160" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">h2</text>

          {/* Host lines */}
          <line x1="48" y1="139" x2="66" y2="150" stroke={LINK} strokeWidth="1"/>
          <line x1="48" y1="157" x2="66" y2="157" stroke={LINK} strokeWidth="1"/>

          {/* Nodes */}
          <circle cx="92" cy="155" r="22" fill={NODE.fill} stroke={NODE.stroke} strokeWidth="1.5"/>
          <text x="92" y="160" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s1</text>
          <text x="92" y="186" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">edge</text>

          <circle cx="186" cy="220" r="22" fill={NODE.fill} stroke={NODE.stroke} strokeWidth="1.5"/>
          <text x="186" y="225" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s2</text>

          <circle cx="92" cy="310" r="22" fill={NODE.fill} stroke="#253548"
            strokeWidth="1.5" strokeDasharray="5,3"/>
          <text x="92" y="315" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s3</text>
          <text x="92" y="341" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">boundary</text>

          {/* Intra links */}
          <line x1="112" y1="165" x2="165" y2="205" stroke={LINK} strokeWidth="1.5"/>
          <line x1="92"  y1="177" x2="92"  y2="288" stroke={LINK} strokeWidth="1.5"/>
          <line x1="165" y1="234" x2="112" y2="298" stroke={LINK} strokeWidth="1.5"/>
        </g>

        {/* ══════════════════════════════
            DOMAIN B
        ══════════════════════════════ */}
        <g
          style={{ opacity: fade("b"), transition: "opacity 0.2s" }}
          onMouseEnter={() => setHovered("b")}
          onMouseLeave={() => setHovered(null)}
          role="group"
          aria-label="Domain B"
        >
          <rect x="314" y="28" width="232" height="384" rx="6"
            fill="none" stroke="#1B2840" strokeWidth="1.5"/>
          <text x="430" y="20" fontFamily="JetBrains Mono, monospace" fontSize="9.5"
            fontWeight="600" fill={LABEL} textAnchor="middle" letterSpacing="3">
            DOMAIN B
          </text>

          <rect x="362" y="36" width="136" height="22" rx="3"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="430" y="51" fontFamily="JetBrains Mono, monospace" fontSize="8.5"
            fill="#3F5066" textAnchor="middle">
            Ryu-B · :6634 / :8081
          </text>

          <line x1="430" y1="58" x2="392" y2="126" stroke="#151E2E"
            strokeWidth="1" strokeDasharray="4,4"/>

          {/* Hosts */}
          <rect x="520" y="207" width="26" height="13" rx="2"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="533" y="217" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">h6</text>
          <rect x="520" y="224" width="26" height="13" rx="2"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="533" y="234" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">h7</text>

          <line x1="520" y1="214" x2="508" y2="220" stroke={LINK} strokeWidth="1"/>
          <line x1="520" y1="230" x2="508" y2="224" stroke={LINK} strokeWidth="1"/>

          <circle cx="392" cy="155" r="22" fill={NODE.fill} stroke="#253548"
            strokeWidth="1.5" strokeDasharray="5,3"/>
          <text x="392" y="160" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s4</text>
          <text x="392" y="186" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">boundary</text>

          <circle cx="486" cy="220" r="22" fill={NODE.fill} stroke={NODE.stroke} strokeWidth="1.5"/>
          <text x="486" y="225" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s5</text>

          <circle cx="392" cy="310" r="22" fill={NODE.fill} stroke="#253548"
            strokeWidth="1.5" strokeDasharray="5,3"/>
          <text x="392" y="315" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s6</text>
          <text x="392" y="341" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">boundary</text>

          <line x1="412" y1="165" x2="465" y2="205" stroke={LINK} strokeWidth="1.5"/>
          <line x1="392" y1="177" x2="392" y2="288" stroke={LINK} strokeWidth="1.5"/>
          <line x1="465" y1="234" x2="412" y2="298" stroke={LINK} strokeWidth="1.5"/>
        </g>

        {/* ══════════════════════════════
            DOMAIN C
        ══════════════════════════════ */}
        <g
          style={{ opacity: fade("c"), transition: "opacity 0.2s" }}
          onMouseEnter={() => setHovered("c")}
          onMouseLeave={() => setHovered(null)}
          role="group"
          aria-label="Domain C"
        >
          <rect x="614" y="28" width="232" height="384" rx="6"
            fill="none" stroke="#1B2840" strokeWidth="1.5"/>
          <text x="730" y="20" fontFamily="JetBrains Mono, monospace" fontSize="9.5"
            fontWeight="600" fill={LABEL} textAnchor="middle" letterSpacing="3">
            DOMAIN C
          </text>

          <rect x="662" y="36" width="136" height="22" rx="3"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="730" y="51" fontFamily="JetBrains Mono, monospace" fontSize="8.5"
            fill="#3F5066" textAnchor="middle">
            Ryu-C · :6653 / :8082
          </text>

          <line x1="730" y1="58" x2="692" y2="126" stroke="#151E2E"
            strokeWidth="1" strokeDasharray="4,4"/>

          <rect x="814" y="207" width="30" height="13" rx="2"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="829" y="217" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">h10</text>
          <rect x="814" y="224" width="30" height="13" rx="2"
            fill="#111A2B" stroke="#1B2840" strokeWidth="1"/>
          <text x="829" y="234" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">h11</text>

          <line x1="814" y1="214" x2="800" y2="220" stroke={LINK} strokeWidth="1"/>
          <line x1="814" y1="230" x2="800" y2="224" stroke={LINK} strokeWidth="1"/>

          <circle cx="692" cy="155" r="22" fill={NODE.fill} stroke="#253548"
            strokeWidth="1.5" strokeDasharray="5,3"/>
          <text x="692" y="160" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s7</text>
          <text x="692" y="186" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">boundary</text>

          <circle cx="786" cy="220" r="22" fill={NODE.fill} stroke={NODE.stroke} strokeWidth="1.5"/>
          <text x="786" y="225" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s8</text>

          <circle cx="692" cy="310" r="22" fill={NODE.fill} stroke={NODE.stroke} strokeWidth="1.5"/>
          <text x="692" y="315" fontFamily="Space Grotesk, sans-serif" fontSize="12"
            fontWeight="700" fill={NODE.text} textAnchor="middle">s9</text>
          <text x="692" y="341" fontFamily="JetBrains Mono, monospace" fontSize="7"
            fill={MUTED} textAnchor="middle">edge</text>

          <line x1="712" y1="165" x2="765" y2="205" stroke={LINK} strokeWidth="1.5"/>
          <line x1="692" y1="177" x2="692" y2="288" stroke={LINK} strokeWidth="1.5"/>
          <line x1="765" y1="234" x2="712" y2="298" stroke={LINK} strokeWidth="1.5"/>
        </g>

        {/* ══════════════════════════════
            INTER-DOMAIN LINKS (always visible)
        ══════════════════════════════ */}

        {/* s3 ↔ s4 — boundary */}
        <line x1="114" y1="307" x2="370" y2="165"
          stroke={INTER} strokeWidth="1.5" strokeDasharray="8,5"/>
        <text x="240" y="220" fontFamily="JetBrains Mono, monospace" fontSize="7.5"
          fill={MUTED} textAnchor="middle" transform="rotate(-31,240,220)">
          s3 — s4
        </text>

        {/* s6 ↔ s7 — boundary */}
        <line x1="414" y1="307" x2="670" y2="165"
          stroke={INTER} strokeWidth="1.5" strokeDasharray="8,5"/>
        <text x="540" y="220" fontFamily="JetBrains Mono, monospace" fontSize="7.5"
          fill={MUTED} textAnchor="middle" transform="rotate(-31,540,220)">
          s6 — s7
        </text>

        {/* s1 ↔ s8 — alternate TE path */}
        <line x1="114" y1="155" x2="764" y2="220"
          stroke={ALT} strokeWidth="1" strokeDasharray="5,5" opacity="0.7"/>
        <text x="440" y="172" fontFamily="JetBrains Mono, monospace" fontSize="7"
          fill={MUTED} textAnchor="middle">
          s1 — s8  (TE alternate path)
        </text>

        {/* ══════════════════════════════
            LEGEND
        ══════════════════════════════ */}
        <g transform="translate(14, 424)">
          <line x1="0" y1="6" x2="18" y2="6" stroke={LINK}  strokeWidth="1.5"/>
          <text x="22" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={MUTED}>Intra-domain</text>

          <line x1="110" y1="6" x2="128" y2="6" stroke={INTER} strokeWidth="1.5" strokeDasharray="6,4"/>
          <text x="132" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={MUTED}>Boundary link</text>

          <line x1="240" y1="6" x2="258" y2="6" stroke={ALT} strokeWidth="1" strokeDasharray="5,4"/>
          <text x="262" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={MUTED}>TE alternate path</text>

          <rect x="390" y="1" width="8" height="8" rx="1" fill="none" stroke="#253548" strokeDasharray="3,2"/>
          <text x="402" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={MUTED}>Boundary switch</text>
        </g>
      </svg>
    </div>
  );
}
