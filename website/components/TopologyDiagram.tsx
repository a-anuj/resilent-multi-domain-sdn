"use client";
import { useState } from "react";

type DomainId = "a" | "b" | "c" | null;

/* ─── colour constants ──────────────────────────────── */
const BG       = "#090E18";
const GRID     = "#111A2B";
const BOX_STR  = "#1B2840";
const NODE_BG  = "#0D1420";
const NODE_STR = "#253548";    // solid switch border
const NODE_BND = "#1E3250";    // dashed boundary switch border
const NODE_TXT = "#C8D4E0";
const CTRL_BG  = "#111A2B";
const CTRL_TXT = "#2D4460";
const LINK     = "#1E3050";    // intra-domain
const INTER    = "#283D58";    // inter-domain dashed
const ALT      = "#2C4668";    // A-C alternate (slightly brighter)
const HOST_BG  = "#0D1420";
const HOST_STR = "#1B2840";
const HOST_TXT = "#2D4460";
const LABEL    = "#4F8EF7";    // domain headings (single accent)
const ANNO     = "#243550";    // link annotations / legend

/* ─── layout constants ──────────────────────────────── */
// Uniform switch Y positions (same for all three domains)
const Y_TOP = 150;   // s1 / s4 / s7
const Y_MID = 270;   // s2 / s5 / s8
const Y_BOT = 390;   // s3 / s6 / s9

// Switch radius
const R = 21;

// Domain A
const A_LEFT  = 82;   // x of s1, s3 (spine)
const A_RIGHT = 192;  // x of s2 (right node)
const A_CX    = 137;  // controller badge center

// Domain B
const B_LEFT  = 400;
const B_RIGHT = 510;
const B_CX    = 455;

// Domain C
const C_LEFT  = 718;
const C_RIGHT = 828;
const C_CX    = 773;

/* ─── helper: single switch node ───────────────────── */
function SwNode({
  cx, cy, label, role,
}: {
  cx: number; cy: number; label: string; role?: "edge" | "boundary" | "";
}) {
  const dashed = role === "boundary";
  return (
    <g>
      <circle
        cx={cx} cy={cy} r={R}
        fill={NODE_BG}
        stroke={dashed ? NODE_BND : NODE_STR}
        strokeWidth="1.5"
        strokeDasharray={dashed ? "5 3" : undefined}
      />
      <text
        x={cx} y={cy + 4.5}
        fontFamily="Space Grotesk, sans-serif"
        fontSize="12" fontWeight="700"
        fill={NODE_TXT} textAnchor="middle"
      >
        {label}
      </text>
      {role && (
        <text
          x={cx} y={cy + R + 16}
          fontFamily="JetBrains Mono, monospace"
          fontSize="7" fill={ANNO} textAnchor="middle"
        >
          {role}
        </text>
      )}
    </g>
  );
}

/* ─── helper: host rectangle + wire ────────────────── */
function Host({
  hx, hy, label, sx, sy, side,
}: {
  hx: number; hy: number; label: string;
  sx: number; sy: number; side: "left" | "right";
}) {
  const HW = label.length > 2 ? 28 : 24, HH = 14;
  /* connection point on the switch edge */
  const swEdgeX = side === "left" ? sx - R : sx + R;
  /* connection point on the host rect */
  const hostEdgeX = side === "left" ? hx + HW : hx;
  return (
    <g>
      <line
        x1={hostEdgeX} y1={hy + HH / 2}
        x2={swEdgeX}   y2={sy}
        stroke={LINK} strokeWidth="1"
      />
      <rect
        x={hx} y={hy} width={HW} height={HH} rx="2"
        fill={HOST_BG} stroke={HOST_STR} strokeWidth="1"
      />
      <text
        x={hx + HW / 2} y={hy + HH / 2 + 3.5}
        fontFamily="JetBrains Mono, monospace"
        fontSize="7" fill={HOST_TXT} textAnchor="middle"
      >
        {label}
      </text>
    </g>
  );
}

/* ─── main component ─────────────────────────────────── */
export function TopologyDiagram() {
  const [hov, setHov] = useState<DomainId>(null);
  const fade = (id: DomainId) =>
    hov === null || hov === id ? 1 : 0.22;

  return (
    <div
      className="diagram-frame"
      role="img"
      aria-label="9-switch 3-domain SDN topology. Domain A: s1 (edge), s2, s3 (boundary). Domain B: s4 (boundary), s5, s6 (boundary). Domain C: s7 (boundary), s8, s9 (edge). Inter-domain: s3–s4, s6–s7, and s1–s8 alternate TE path."
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 900 520"
        style={{ maxWidth: "100%", height: "auto" }}
        aria-hidden="true" focusable="false"
      >
        {/* ── BG ── */}
        <rect width="900" height="520" fill={BG} />
        <defs>
          <pattern id="tg" width="44" height="44" patternUnits="userSpaceOnUse">
            <path d="M44 0L0 0 0 44" fill="none" stroke={GRID} strokeWidth="1" />
          </pattern>
        </defs>
        <rect width="900" height="520" fill="url(#tg)" />

        {/* ═══════════════════════════════════════════════
            INTER-DOMAIN LINKS — drawn first (behind nodes)
        ═══════════════════════════════════════════════ */}

        {/* s3 ↔ s4  (A boundary → B boundary) */}
        <line
          x1={A_LEFT} y1={Y_BOT}
          x2={B_LEFT} y2={Y_TOP}
          stroke={INTER} strokeWidth="1.5" strokeDasharray="8 5"
        />

        {/* s6 ↔ s7  (B boundary → C boundary) */}
        <line
          x1={B_LEFT} y1={Y_BOT}
          x2={C_LEFT} y2={Y_TOP}
          stroke={INTER} strokeWidth="1.5" strokeDasharray="8 5"
        />

        {/* s1 ↔ s8  (A-C alternate / TE path) */}
        <line
          x1={A_LEFT} y1={Y_TOP}
          x2={C_RIGHT} y2={Y_MID}
          stroke={ALT} strokeWidth="1" strokeDasharray="5 5" opacity="0.55"
        />

        {/* ═══════════════════════════════════════
            DOMAIN A
        ═══════════════════════════════════════ */}
        <g
          style={{ opacity: fade("a"), transition: "opacity 0.2s" }}
          onMouseEnter={() => setHov("a")}
          onMouseLeave={() => setHov(null)}
          role="group"
          aria-label="Domain A"
        >
          {/* Box */}
          <rect x="10" y="25" width="250" height="455" rx="6"
            fill="none" stroke={BOX_STR} strokeWidth="1.5" />

          {/* Domain label */}
          <text x={A_CX} y="18" fontFamily="JetBrains Mono, monospace"
            fontSize="9" fontWeight="600" fill={LABEL}
            textAnchor="middle" letterSpacing="3">DOMAIN A</text>

          {/* Controller badge */}
          <rect x={A_CX - 76} y="33" width="152" height="20" rx="3"
            fill={CTRL_BG} stroke={BOX_STR} strokeWidth="1" />
          <text x={A_CX} y="47" fontFamily="JetBrains Mono, monospace"
            fontSize="7.5" fill={CTRL_TXT} textAnchor="middle">
            Ryu-A  ·  :6633 / :8080
          </text>

          {/* Guide: controller → s1 */}
          <line x1={A_CX} y1="53" x2={A_LEFT} y2={Y_TOP - R}
            stroke={GRID} strokeWidth="0.8" strokeDasharray="3 4" />

          {/* Intra links */}
          <line x1={A_LEFT} y1={Y_TOP} x2={A_RIGHT} y2={Y_MID}
            stroke={LINK} strokeWidth="1.5" />
          <line x1={A_LEFT} y1={Y_TOP} x2={A_LEFT}  y2={Y_BOT}
            stroke={LINK} strokeWidth="1.5" />
          <line x1={A_RIGHT} y1={Y_MID} x2={A_LEFT} y2={Y_BOT}
            stroke={LINK} strokeWidth="1.5" />

          {/* Hosts: h1 and h2 to the LEFT of s1 */}
          <Host hx={16} hy={Y_TOP - 18} label="h1" sx={A_LEFT} sy={Y_TOP} side="left" />
          <Host hx={16} hy={Y_TOP +  6} label="h2" sx={A_LEFT} sy={Y_TOP} side="left" />

          {/* Switches */}
          <SwNode cx={A_LEFT}  cy={Y_TOP} label="s1" role="edge" />
          <SwNode cx={A_RIGHT} cy={Y_MID} label="s2" />
          <SwNode cx={A_LEFT}  cy={Y_BOT} label="s3" role="boundary" />
        </g>

        {/* ═══════════════════════════════════════
            DOMAIN B
        ═══════════════════════════════════════ */}
        <g
          style={{ opacity: fade("b"), transition: "opacity 0.2s" }}
          onMouseEnter={() => setHov("b")}
          onMouseLeave={() => setHov(null)}
          role="group"
          aria-label="Domain B"
        >
          <rect x="328" y="25" width="250" height="455" rx="6"
            fill="none" stroke={BOX_STR} strokeWidth="1.5" />

          <text x={B_CX} y="18" fontFamily="JetBrains Mono, monospace"
            fontSize="9" fontWeight="600" fill={LABEL}
            textAnchor="middle" letterSpacing="3">DOMAIN B</text>

          <rect x={B_CX - 76} y="33" width="152" height="20" rx="3"
            fill={CTRL_BG} stroke={BOX_STR} strokeWidth="1" />
          <text x={B_CX} y="47" fontFamily="JetBrains Mono, monospace"
            fontSize="7.5" fill={CTRL_TXT} textAnchor="middle">
            Ryu-B  ·  :6634 / :8081
          </text>

          <line x1={B_CX} y1="53" x2={B_LEFT} y2={Y_TOP - R}
            stroke={GRID} strokeWidth="0.8" strokeDasharray="3 4" />

          <line x1={B_LEFT} y1={Y_TOP} x2={B_RIGHT} y2={Y_MID}
            stroke={LINK} strokeWidth="1.5" />
          <line x1={B_LEFT} y1={Y_TOP} x2={B_LEFT}  y2={Y_BOT}
            stroke={LINK} strokeWidth="1.5" />
          <line x1={B_RIGHT} y1={Y_MID} x2={B_LEFT} y2={Y_BOT}
            stroke={LINK} strokeWidth="1.5" />

          {/* Hosts: h6 and h7 to the RIGHT of s5 */}
          <Host hx={B_RIGHT + R + 6} hy={Y_MID - 18} label="h6" sx={B_RIGHT} sy={Y_MID} side="right" />
          <Host hx={B_RIGHT + R + 6} hy={Y_MID +  6} label="h7" sx={B_RIGHT} sy={Y_MID} side="right" />

          <SwNode cx={B_LEFT}  cy={Y_TOP} label="s4" role="boundary" />
          <SwNode cx={B_RIGHT} cy={Y_MID} label="s5" />
          <SwNode cx={B_LEFT}  cy={Y_BOT} label="s6" role="boundary" />
        </g>

        {/* ═══════════════════════════════════════
            DOMAIN C
        ═══════════════════════════════════════ */}
        <g
          style={{ opacity: fade("c"), transition: "opacity 0.2s" }}
          onMouseEnter={() => setHov("c")}
          onMouseLeave={() => setHov(null)}
          role="group"
          aria-label="Domain C"
        >
          <rect x="646" y="25" width="250" height="455" rx="6"
            fill="none" stroke={BOX_STR} strokeWidth="1.5" />

          <text x={C_CX} y="18" fontFamily="JetBrains Mono, monospace"
            fontSize="9" fontWeight="600" fill={LABEL}
            textAnchor="middle" letterSpacing="3">DOMAIN C</text>

          <rect x={C_CX - 76} y="33" width="152" height="20" rx="3"
            fill={CTRL_BG} stroke={BOX_STR} strokeWidth="1" />
          <text x={C_CX} y="47" fontFamily="JetBrains Mono, monospace"
            fontSize="7.5" fill={CTRL_TXT} textAnchor="middle">
            Ryu-C  ·  :6653 / :8082
          </text>

          <line x1={C_CX} y1="53" x2={C_LEFT} y2={Y_TOP - R}
            stroke={GRID} strokeWidth="0.8" strokeDasharray="3 4" />

          <line x1={C_LEFT} y1={Y_TOP} x2={C_RIGHT} y2={Y_MID}
            stroke={LINK} strokeWidth="1.5" />
          <line x1={C_LEFT} y1={Y_TOP} x2={C_LEFT}  y2={Y_BOT}
            stroke={LINK} strokeWidth="1.5" />
          <line x1={C_RIGHT} y1={Y_MID} x2={C_LEFT} y2={Y_BOT}
            stroke={LINK} strokeWidth="1.5" />

          {/* Hosts: h10 and h11 to the RIGHT of s8 */}
          <Host hx={C_RIGHT + R + 6} hy={Y_MID - 18} label="h10" sx={C_RIGHT} sy={Y_MID} side="right" />
          <Host hx={C_RIGHT + R + 6} hy={Y_MID +  6} label="h11" sx={C_RIGHT} sy={Y_MID} side="right" />

          <SwNode cx={C_LEFT}  cy={Y_TOP} label="s7" role="boundary" />
          <SwNode cx={C_RIGHT} cy={Y_MID} label="s8" />
          <SwNode cx={C_LEFT}  cy={Y_BOT} label="s9" role="edge" />
        </g>

        {/* ═══════════════════════════════════════
            ANNOTATIONS — inter-domain labels
        ═══════════════════════════════════════ */}
        {/* Label midpoint of s3→s4 line */}
        <text
          x={(A_LEFT + B_LEFT) / 2}
          y={(Y_BOT + Y_TOP) / 2 + 6}
          fontFamily="JetBrains Mono, monospace" fontSize="7" fill={ANNO}
          textAnchor="middle"
          transform={`rotate(-36, ${(A_LEFT + B_LEFT) / 2}, ${(Y_BOT + Y_TOP) / 2 + 6})`}
        >
          s3 — s4
        </text>
        {/* Label midpoint of s6→s7 line */}
        <text
          x={(B_LEFT + C_LEFT) / 2}
          y={(Y_BOT + Y_TOP) / 2 + 6}
          fontFamily="JetBrains Mono, monospace" fontSize="7" fill={ANNO}
          textAnchor="middle"
          transform={`rotate(-36, ${(B_LEFT + C_LEFT) / 2}, ${(Y_BOT + Y_TOP) / 2 + 6})`}
        >
          s6 — s7
        </text>
        {/* Label midpoint of s1→s8 alternate */}
        <text
          x={(A_LEFT + C_RIGHT) / 2}
          y={(Y_TOP + Y_MID) / 2 - 10}
          fontFamily="JetBrains Mono, monospace" fontSize="7" fill={ANNO}
          textAnchor="middle"
        >
          s1 — s8  (TE alternate path)
        </text>

        {/* ═══════════════════════════════════════
            LEGEND
        ═══════════════════════════════════════ */}
        <g transform="translate(10, 496)">
          {/* Solid switch */}
          <circle cx="8" cy="6" r="5" fill="none" stroke={NODE_STR} strokeWidth="1.5" />
          <text x="17" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={ANNO}>Switch</text>

          {/* Boundary switch */}
          <circle cx="80" cy="6" r="5" fill="none" stroke={NODE_BND} strokeWidth="1.5" strokeDasharray="3 2" />
          <text x="89" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={ANNO}>Boundary switch</text>

          {/* Intra link */}
          <line x1="210" y1="6" x2="230" y2="6" stroke={LINK} strokeWidth="1.5" />
          <text x="234" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={ANNO}>Intra-domain</text>

          {/* Inter-domain */}
          <line x1="330" y1="6" x2="350" y2="6" stroke={INTER} strokeWidth="1.5" strokeDasharray="6 4" />
          <text x="354" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={ANNO}>Boundary link</text>

          {/* Alternate TE */}
          <line x1="452" y1="6" x2="472" y2="6" stroke={ALT} strokeWidth="1" strokeDasharray="5 4" opacity="0.6" />
          <text x="476" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={ANNO}>TE alternate</text>

          {/* Host */}
          <rect x="565" y="0" width="18" height="12" rx="2" fill="none" stroke={HOST_STR} strokeWidth="1" />
          <text x="587" y="10" fontFamily="JetBrains Mono, monospace" fontSize="7.5" fill={ANNO}>Host</text>
        </g>
      </svg>
    </div>
  );
}
