"use client";
import { useState } from "react";

type DomainId = "a" | "b" | "c" | null;

export function TopologyDiagram() {
  const [hovered, setHovered] = useState<DomainId>(null);

  const domainOpacity = (id: DomainId) =>
    hovered === null || hovered === id ? 1 : 0.35;

  return (
    <div className="diagram-frame" role="img" aria-label="9-switch 3-domain SDN topology. Domain A: switches s1, s2, s3 controlled by Ryu A on port 6633. Domain B: switches s4, s5, s6 on port 6634. Domain C: switches s7, s8, s9 on port 6653. Domains connected by inter-domain boundary links.">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 860 460"
        style={{ maxWidth: "100%", height: "auto" }}
        aria-hidden="true"
        focusable="false"
      >
        {/* Background grid */}
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#263A50" strokeWidth="0.5" opacity="0.4"/>
          </pattern>
        </defs>
        <rect width="860" height="460" fill="#08111F"/>
        <rect width="860" height="460" fill="url(#grid)"/>

        {/* === DOMAIN A === */}
        <g
          style={{ opacity: domainOpacity("a"), transition: "opacity 0.25s ease", cursor: "pointer" }}
          onMouseEnter={() => setHovered("a")}
          onMouseLeave={() => setHovered(null)}
          role="group"
          aria-label="Domain A: switches s1, s2, s3"
        >
          <rect x="16" y="30" width="230" height="400" rx="8" fill="#0D1B2A" stroke="#38D6E8" strokeWidth="1.5" opacity="0.7"/>
          <text x="131" y="22" fontFamily="Space Grotesk, sans-serif" fontSize="11" fontWeight="700" fill="#38D6E8" textAnchor="middle" letterSpacing="2">DOMAIN A</text>

          {/* Controller A */}
          <rect x="68" y="42" width="126" height="26" rx="4" fill="#112338" stroke="#38D6E8" strokeWidth="1"/>
          <text x="131" y="59" fontFamily="JetBrains Mono, monospace" fontSize="9" fill="#38D6E8" textAnchor="middle">Ryu-A  :6633/:8080</text>

          {/* s1 */}
          <circle cx="80" cy="160" r="26" fill="#112338" stroke="#38D6E8" strokeWidth="2"/>
          <text x="80" y="165" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s1</text>
          <text x="80" y="195" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">edge</text>

          {/* s2 */}
          <circle cx="185" cy="230" r="26" fill="#112338" stroke="#38D6E8" strokeWidth="2"/>
          <text x="185" y="235" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s2</text>

          {/* s3 */}
          <circle cx="80" cy="330" r="26" fill="#112338" stroke="#38D6E8" strokeWidth="2" strokeDasharray="5,3"/>
          <text x="80" y="335" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s3</text>
          <text x="80" y="364" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">boundary</text>

          {/* Hosts h1, h2 */}
          <rect x="20" y="140" width="26" height="16" rx="3" fill="#263A50" stroke="#A8B8C8" strokeWidth="1"/>
          <text x="33" y="152" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#A8B8C8" textAnchor="middle">h1</text>
          <rect x="20" y="162" width="26" height="16" rx="3" fill="#263A50" stroke="#A8B8C8" strokeWidth="1"/>
          <text x="33" y="174" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#A8B8C8" textAnchor="middle">h2</text>

          {/* A intra links */}
          <line x1="131" y1="68" x2="131" y2="138" stroke="#38D6E8" strokeWidth="1" strokeDasharray="4,4" opacity="0.4"/>
          <line x1="46" y1="150" x2="54" y2="156" stroke="#A8B8C8" strokeWidth="1"/>
          <line x1="46" y1="168" x2="54" y2="163" stroke="#A8B8C8" strokeWidth="1"/>
          <line x1="104" y1="170" x2="163" y2="215" stroke="#38D6E8" strokeWidth="1.5"/>
          <line x1="80" y1="186" x2="80" y2="304" stroke="#38D6E8" strokeWidth="1.5"/>
          <line x1="160" y1="244" x2="104" y2="316" stroke="#38D6E8" strokeWidth="1.5"/>

          {/* 1G label */}
          <text x="152" y="195" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">1G</text>
          <text x="64" y="248" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">1G</text>
        </g>

        {/* === DOMAIN B === */}
        <g
          style={{ opacity: domainOpacity("b"), transition: "opacity 0.25s ease", cursor: "pointer" }}
          onMouseEnter={() => setHovered("b")}
          onMouseLeave={() => setHovered(null)}
          role="group"
          aria-label="Domain B: switches s4, s5, s6"
        >
          <rect x="315" y="30" width="230" height="400" rx="8" fill="#0D1B2A" stroke="#5B8CFF" strokeWidth="1.5" opacity="0.7"/>
          <text x="430" y="22" fontFamily="Space Grotesk, sans-serif" fontSize="11" fontWeight="700" fill="#5B8CFF" textAnchor="middle" letterSpacing="2">DOMAIN B</text>

          <rect x="367" y="42" width="126" height="26" rx="4" fill="#112338" stroke="#5B8CFF" strokeWidth="1"/>
          <text x="430" y="59" fontFamily="JetBrains Mono, monospace" fontSize="9" fill="#5B8CFF" textAnchor="middle">Ryu-B  :6634/:8081</text>

          {/* s4 */}
          <circle cx="380" cy="160" r="26" fill="#112338" stroke="#5B8CFF" strokeWidth="2" strokeDasharray="5,3"/>
          <text x="380" y="165" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s4</text>
          <text x="380" y="195" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">boundary</text>

          {/* s5 */}
          <circle cx="480" cy="230" r="26" fill="#112338" stroke="#5B8CFF" strokeWidth="2"/>
          <text x="480" y="235" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s5</text>

          {/* s6 */}
          <circle cx="380" cy="330" r="26" fill="#112338" stroke="#5B8CFF" strokeWidth="2" strokeDasharray="5,3"/>
          <text x="380" y="335" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s6</text>
          <text x="380" y="364" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">boundary</text>

          {/* Hosts h6, h7 */}
          <rect x="510" y="216" width="26" height="16" rx="3" fill="#263A50" stroke="#A8B8C8" strokeWidth="1"/>
          <text x="523" y="228" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#A8B8C8" textAnchor="middle">h6</text>
          <rect x="510" y="236" width="26" height="16" rx="3" fill="#263A50" stroke="#A8B8C8" strokeWidth="1"/>
          <text x="523" y="248" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#A8B8C8" textAnchor="middle">h7</text>

          {/* B intra links */}
          <line x1="430" y1="68" x2="430" y2="138" stroke="#5B8CFF" strokeWidth="1" strokeDasharray="4,4" opacity="0.4"/>
          <line x1="404" y1="170" x2="458" y2="215" stroke="#5B8CFF" strokeWidth="1.5"/>
          <line x1="380" y1="186" x2="380" y2="304" stroke="#5B8CFF" strokeWidth="1.5"/>
          <line x1="456" y1="244" x2="404" y2="316" stroke="#5B8CFF" strokeWidth="1.5"/>
          <line x1="506" y1="224" x2="506" y2="224" stroke="#A8B8C8" strokeWidth="1"/>
        </g>

        {/* === DOMAIN C === */}
        <g
          style={{ opacity: domainOpacity("c"), transition: "opacity 0.25s ease", cursor: "pointer" }}
          onMouseEnter={() => setHovered("c")}
          onMouseLeave={() => setHovered(null)}
          role="group"
          aria-label="Domain C: switches s7, s8, s9"
        >
          <rect x="614" y="30" width="230" height="400" rx="8" fill="#0D1B2A" stroke="#52D6A0" strokeWidth="1.5" opacity="0.7"/>
          <text x="729" y="22" fontFamily="Space Grotesk, sans-serif" fontSize="11" fontWeight="700" fill="#52D6A0" textAnchor="middle" letterSpacing="2">DOMAIN C</text>

          <rect x="666" y="42" width="126" height="26" rx="4" fill="#112338" stroke="#52D6A0" strokeWidth="1"/>
          <text x="729" y="59" fontFamily="JetBrains Mono, monospace" fontSize="9" fill="#52D6A0" textAnchor="middle">Ryu-C  :6653/:8082</text>

          {/* s7 */}
          <circle cx="679" cy="160" r="26" fill="#112338" stroke="#52D6A0" strokeWidth="2" strokeDasharray="5,3"/>
          <text x="679" y="165" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s7</text>
          <text x="679" y="195" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">boundary</text>

          {/* s8 */}
          <circle cx="779" cy="230" r="26" fill="#112338" stroke="#52D6A0" strokeWidth="2"/>
          <text x="779" y="235" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s8</text>

          {/* s9 */}
          <circle cx="679" cy="330" r="26" fill="#112338" stroke="#52D6A0" strokeWidth="2"/>
          <text x="679" y="335" fontFamily="Space Grotesk, sans-serif" fontSize="13" fontWeight="700" fill="#EAF2F8" textAnchor="middle">s9</text>
          <text x="679" y="364" fontFamily="JetBrains Mono, monospace" fontSize="7" fill="#A8B8C8" textAnchor="middle">edge</text>

          {/* Hosts h10, h11 */}
          <rect x="809" y="216" width="30" height="16" rx="3" fill="#263A50" stroke="#A8B8C8" strokeWidth="1"/>
          <text x="824" y="228" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#A8B8C8" textAnchor="middle">h10</text>
          <rect x="809" y="236" width="30" height="16" rx="3" fill="#263A50" stroke="#A8B8C8" strokeWidth="1"/>
          <text x="824" y="248" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#A8B8C8" textAnchor="middle">h11</text>

          {/* C intra links */}
          <line x1="729" y1="68" x2="729" y2="138" stroke="#52D6A0" strokeWidth="1" strokeDasharray="4,4" opacity="0.4"/>
          <line x1="703" y1="170" x2="756" y2="215" stroke="#52D6A0" strokeWidth="1.5"/>
          <line x1="679" y1="186" x2="679" y2="304" stroke="#52D6A0" strokeWidth="1.5"/>
          <line x1="755" y1="244" x2="703" y2="316" stroke="#52D6A0" strokeWidth="1.5"/>
        </g>

        {/* === INTER-DOMAIN LINKS (always visible) === */}
        {/* A-B: s3 ↔ s4 */}
        <line x1="106" y1="328" x2="354" y2="172" stroke="#F4B942" strokeWidth="2" strokeDasharray="7,4" opacity="0.9"/>
        <text x="228" y="238" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#F4B942" textAnchor="middle" transform="rotate(-32,228,238)">s3 ↔ s4 · 1G</text>

        {/* B-C: s6 ↔ s7 */}
        <line x1="406" y1="328" x2="654" y2="172" stroke="#F4B942" strokeWidth="2" strokeDasharray="7,4" opacity="0.9"/>
        <text x="528" y="238" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#F4B942" textAnchor="middle" transform="rotate(-32,528,238)">s6 ↔ s7 · 1G</text>

        {/* A-C diagonal s1 ↔ s8 */}
        <line x1="106" y1="160" x2="753" y2="230" stroke="#FF647C" strokeWidth="1.5" strokeDasharray="5,4" opacity="0.6"/>
        <text x="430" y="182" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill="#FF647C" textAnchor="middle">s1 ↔ s8  (A–C TE alternate path)</text>

        {/* Legend */}
        <g transform="translate(16, 440)">
          <line x1="0" y1="8" x2="22" y2="8" stroke="#38D6E8" strokeWidth="2"/>
          <text x="26" y="12" fontFamily="Inter, sans-serif" fontSize="8" fill="#A8B8C8">Domain A</text>
          <line x1="90" y1="8" x2="112" y2="8" stroke="#5B8CFF" strokeWidth="2"/>
          <text x="116" y="12" fontFamily="Inter, sans-serif" fontSize="8" fill="#A8B8C8">Domain B</text>
          <line x1="180" y1="8" x2="202" y2="8" stroke="#52D6A0" strokeWidth="2"/>
          <text x="206" y="12" fontFamily="Inter, sans-serif" fontSize="8" fill="#A8B8C8">Domain C</text>
          <line x1="270" y1="8" x2="292" y2="8" stroke="#F4B942" strokeWidth="2" strokeDasharray="6,3"/>
          <text x="296" y="12" fontFamily="Inter, sans-serif" fontSize="8" fill="#A8B8C8">Inter-domain boundary</text>
          <line x1="430" y1="8" x2="452" y2="8" stroke="#FF647C" strokeWidth="1.5" strokeDasharray="5,3"/>
          <text x="456" y="12" fontFamily="Inter, sans-serif" fontSize="8" fill="#A8B8C8">A–C alternate TE path</text>
        </g>
      </svg>
    </div>
  );
}
