#!/usr/bin/env python3
"""
experiments/plot_eval_figures.py
---------------------------------
Generates publication-quality comparative evaluation figures for
Defended vs. Undefended Southbound PacketIn Flood experiments:

  - fig4_defended_vs_undefended_latency.png:
      Side-by-side comparison of Domain-A latencies across Baseline, Attack, and Recovery.
  - fig5_probe_health_reliability.png:
      Probe success & failure rates by phase (including pre-fix vs. post-fix baseline).
  - fig6_multidomain_spillover.png:
      Cross-domain latency collateral spillover (Domains A, B, and C).
  - fig7_attack_timeline_profile.png:
      End-to-end time-series timeline across the 150-second experiment lifecycle.

All figures are saved to results/figures/ as PNG and PDF.
"""

import json
import glob
import os
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = _ROOT / "results"
EVAL_DIR = RESULTS_DIR / "after_ha"
FIG_DIR = RESULTS_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

# Modern plotting style
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.labelsize": 11,
    "axes.labelweight": "semibold",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "grid.alpha": 0.35,
    "grid.linestyle": "--",
    "figure.dpi": 200,
    "savefig.dpi": 250,
})

# Color palette
C_UNDEF = "#E63946"   # Crimson Red
C_DEF   = "#2A9D8F"   # Teal / Emerald
C_BASE  = "#457B9D"   # Soft Steel Blue
C_WARN  = "#F4A261"   # Amber Orange
C_DARK  = "#1D3557"   # Navy Dark

def load_data():
    summary_files = sorted(glob.glob(str(EVAL_DIR / "run_*_summary.json")), 
                           key=lambda x: int(os.path.basename(x).split('_')[1]))
    runs = []
    for f in summary_files:
        with open(f) as fp:
            runs.append(json.load(fp))
    return runs

runs = load_data()
undef_runs = [r for r in runs if r["condition"] == "undefended"]
def_runs = [r for r in runs if r["condition"] == "defended"]

print(f"Loaded {len(undef_runs)} undefended runs and {len(def_runs)} defended runs.")


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 1: Latency Comparison across Phases (Domain A)
# ─────────────────────────────────────────────────────────────────────────────
def plot_latency_comparison():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.5), gridspec_kw={'width_ratios': [1.8, 1.2]})
    
    phases = ["Baseline", "During Attack", "Recovery"]
    
    # Compute medians and standard deviations
    undef_medians = [
        np.median([r["latency_ms"]["baseline"]["A"]["median_ms"] for r in undef_runs]),
        np.median([r["latency_ms"]["during"]["A"]["median_ms"] for r in undef_runs]),
        np.median([r["latency_ms"]["recovery"]["A"]["median_ms"] for r in undef_runs])
    ]
    def_medians = [
        np.median([r["latency_ms"]["baseline"]["A"]["median_ms"] for r in def_runs]),
        np.median([r["latency_ms"]["during"]["A"]["median_ms"] for r in def_runs]),
        np.median([r["latency_ms"]["recovery"]["A"]["median_ms"] for r in def_runs])
    ]

    x = np.arange(len(phases))
    width = 0.35

    rects1 = ax1.bar(x - width/2, undef_medians, width, label="Undefended (No CB)", color=C_UNDEF, alpha=0.9, edgecolor="black", linewidth=0.8)
    rects2 = ax1.bar(x + width/2, def_medians, width, label="Defended (Circuit Breaker)", color=C_DEF, alpha=0.9, edgecolor="black", linewidth=0.8)

    # Scatter points for individual runs
    for i, phase_key in enumerate(["baseline", "during", "recovery"]):
        u_pts = [r["latency_ms"][phase_key]["A"]["median_ms"] for r in undef_runs]
        d_pts = [r["latency_ms"][phase_key]["A"]["median_ms"] for r in def_runs]
        ax1.scatter([x[i] - width/2]*len(u_pts) + np.random.normal(0, 0.02, len(u_pts)), u_pts, color="#8B0000", s=35, zorder=3, alpha=0.8)
        ax1.scatter([x[i] + width/2]*len(d_pts) + np.random.normal(0, 0.02, len(d_pts)), d_pts, color="#1D4E47", s=35, zorder=3, alpha=0.8)

    ax1.set_ylabel("Median Response Latency (ms)")
    ax1.set_title("Domain-A Controller Latency by Phase (N=5 per condition)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(phases)
    ax1.grid(True, axis="y")
    ax1.legend(loc="upper left", frameon=True)

    # Annotate bars
    for rect in rects1:
        h = rect.get_height()
        ax1.annotate(f"{h:.1f} ms",
                    xy=(rect.get_x() + rect.get_width() / 2, h),
                    xytext=(0, 4), textcoords="offset points",
                    ha='center', va='bottom', fontsize=10, fontweight='bold', color=C_UNDEF)
    for rect in rects2:
        h = rect.get_height()
        ax1.annotate(f"{h:.1f} ms",
                    xy=(rect.get_x() + rect.get_width() / 2, h),
                    xytext=(0, 4), textcoords="offset points",
                    ha='center', va='bottom', fontsize=10, fontweight='bold', color=C_DEF)

    # Logarithmic zoom panel on Attack & Recovery
    log_phases = ["Attack Phase", "Recovery Phase"]
    x_sub = np.arange(len(log_phases))
    ax2.bar(x_sub - width/2, [undef_medians[1], undef_medians[2]], width, label="Undefended", color=C_UNDEF, alpha=0.9, edgecolor="black")
    ax2.bar(x_sub + width/2, [def_medians[1], def_medians[2]], width, label="Defended", color=C_DEF, alpha=0.9, edgecolor="black")
    ax2.set_yscale("log")
    ax2.set_title("Log-Scale Detail (Attack vs Recovery)")
    ax2.set_xticks(x_sub)
    ax2.set_xticklabels(log_phases)
    ax2.set_ylabel("Latency (ms, Log Scale)")
    ax2.grid(True, which="both", axis="y")

    # Annotations on reduction
    red_atk = (1 - def_medians[1] / undef_medians[1]) * 100
    red_rec = (1 - def_medians[2] / undef_medians[2]) * 100
    ax2.annotate(f"-{red_atk:.1f}%", xy=(0, def_medians[1]), xytext=(0.15, def_medians[1]*3),
                 arrowprops=dict(arrowstyle="->", color="black", lw=1), fontweight="bold", fontsize=10)
    ax2.annotate(f"-{red_rec:.1f}%", xy=(1, def_medians[2]), xytext=(1.15, def_medians[2]*3),
                 arrowprops=dict(arrowstyle="->", color="black", lw=1), fontweight="bold", fontsize=10)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig4_defended_vs_undefended_latency.png")
    fig.savefig(FIG_DIR / "fig4_defended_vs_undefended_latency.pdf")
    plt.close(fig)
    print("Saved fig4_defended_vs_undefended_latency")


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 2: Probe Health & Reliability Analysis
# ─────────────────────────────────────────────────────────────────────────────
def plot_probe_health():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # Panel 1: Post-Fix Probe Success Rate by Phase in Defended Runs
    phases = ["Baseline (30s)", "Attack Flood (60s)", "Recovery (60s)"]
    
    # Extract total vs failed across all 5 defended runs
    base_fails = sum(r["probes"]["by_phase"]["baseline"]["A"]["failed"] for r in def_runs)
    base_total = sum(r["latency_ms"]["baseline"]["A"]["total_probes"] for r in def_runs)
    
    dur_fails = sum(r["probes"]["by_phase"]["during"]["A"]["failed"] for r in def_runs)
    dur_total = sum(r["latency_ms"]["during"]["A"]["total_probes"] for r in def_runs)

    rec_fails = sum(r["probes"]["by_phase"]["recovery"]["A"]["failed"] for r in def_runs)
    rec_total = sum(r["latency_ms"]["recovery"]["A"]["total_probes"] for r in def_runs)

    success_rates = [
        (base_total - base_fails) / base_total * 100,
        (dur_total - dur_fails) / dur_total * 100,
        (rec_total - rec_fails) / rec_total * 100
    ]
    fail_rates = [100 - s for s in success_rates]

    x = np.arange(len(phases))
    bars_succ = ax1.bar(x, success_rates, width=0.5, color=C_DEF, label="Successful Probes (HTTP 200)", edgecolor="black")
    bars_fail = ax1.bar(x, fail_rates, bottom=success_rates, width=0.5, color=C_WARN, label="Restart Window Drops (~4.4s)", edgecolor="black")

    ax1.set_ylabel("Probe Availability (%)")
    ax1.set_ylim(80, 105)
    ax1.set_title("Probe Availability by Phase (Post-Fix Defended Runs)")
    ax1.set_xticks(x)
    ax1.set_xticklabels(phases)
    ax1.grid(True, axis="y")
    ax1.legend(loc="lower left")

    for i, s in enumerate(success_rates):
        ax1.text(i, s - 4, f"{s:.1f}%\n({base_total - base_fails if i==0 else (dur_total - dur_fails if i==1 else rec_total - rec_fails)}/{base_total if i==0 else (dur_total if i==1 else rec_total)})",
                 ha="center", va="top", color="white", fontweight="bold", fontsize=10)
        if fail_rates[i] > 0:
            ax1.text(i, 101, f"{fail_rates[i]:.1f}% drop\n(Reboot window)", ha="center", va="bottom", color="#B25900", fontsize=9, fontweight="bold")

    # Panel 2: Before vs After Fix Comparison (Baseline Probe Failures)
    # Before fix: 22.67% failed probes in baseline due to triangle broadcast storm
    # After fix: 0.0% failed probes
    categories = ["Pre-Fix (Broadcast Storm)", "Post-Fix (Hypotenuse Drop)"]
    baseline_failure_pct = [22.67, 0.0]
    baseline_success_pct = [77.33, 100.0]

    x2 = np.arange(len(categories))
    b1 = ax2.bar(x2, baseline_success_pct, width=0.45, color=C_BASE, label="Operational", edgecolor="black")
    b2 = ax2.bar(x2, baseline_failure_pct, bottom=baseline_success_pct, width=0.45, color=C_UNDEF, label="False Trigger Outage", edgecolor="black")
    ax2.set_ylabel("Baseline Health Probe Rate (%)")
    ax2.set_ylim(60, 108)
    ax2.set_title("Baseline Probe Health: Pre-Fix vs. Post-Fix")
    ax2.set_xticks(x2)
    ax2.set_xticklabels(categories)
    ax2.grid(True, axis="y")
    ax2.legend(loc="lower left")

    ax2.annotate("0% False Triggers\n100% Probe Success",
                 xy=(1, 100), xytext=(0.85, 85),
                 arrowprops=dict(arrowstyle="->", color="black", lw=1.2),
                 fontweight="bold", fontsize=10, color="#1D4E47")
    ax2.annotate("22.7% False Probe Outages\n(Loop Storm saturating queue)",
                 xy=(0, 90), xytext=(-0.25, 70),
                 arrowprops=dict(arrowstyle="->", color="black", lw=1.2),
                 fontweight="bold", fontsize=9, color="#8B0000")

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig5_probe_health_reliability.png")
    fig.savefig(FIG_DIR / "fig5_probe_health_reliability.pdf")
    plt.close(fig)
    print("Saved fig5_probe_health_reliability")


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 3: Cross-Domain Multi-Controller Spillover (Domains A, B, C)
# ─────────────────────────────────────────────────────────────────────────────
def plot_multidomain_spillover():
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    domains = ["Domain A (Target)", "Domain B (Neighbor)", "Domain C (Transit)"]
    x = np.arange(len(domains))
    width = 0.35

    # Attack Phase Medians
    u_atk = [
        np.median([r["latency_ms"]["during"]["A"]["median_ms"] for r in undef_runs]),
        np.median([r["latency_ms"]["during"]["B"]["median_ms"] for r in undef_runs]),
        np.median([r["latency_ms"]["during"]["C"]["median_ms"] for r in undef_runs]),
    ]
    d_atk = [
        np.median([r["latency_ms"]["during"]["A"]["median_ms"] for r in def_runs]),
        np.median([r["latency_ms"]["during"]["B"]["median_ms"] for r in def_runs]),
        np.median([r["latency_ms"]["during"]["C"]["median_ms"] for r in def_runs]),
    ]

    # Recovery Phase Medians
    u_rec = [
        np.median([r["latency_ms"]["recovery"]["A"]["median_ms"] for r in undef_runs]),
        np.median([r["latency_ms"]["recovery"]["B"]["median_ms"] for r in undef_runs]),
        np.median([r["latency_ms"]["recovery"]["C"]["median_ms"] for r in undef_runs]),
    ]
    d_rec = [
        np.median([r["latency_ms"]["recovery"]["A"]["median_ms"] for r in def_runs]),
        np.median([r["latency_ms"]["recovery"]["B"]["median_ms"] for r in def_runs]),
        np.median([r["latency_ms"]["recovery"]["C"]["median_ms"] for r in def_runs]),
    ]

    # Panel 1: Attack Phase Spillover
    r1 = ax1.bar(x - width/2, u_atk, width, label="Undefended", color=C_UNDEF, alpha=0.9, edgecolor="black")
    r2 = ax1.bar(x + width/2, d_atk, width, label="Defended (CB)", color=C_DEF, alpha=0.9, edgecolor="black")
    ax1.set_ylabel("Median Latency (ms)")
    ax1.set_title("Attack Phase: Cross-Domain Controller Latency")
    ax1.set_xticks(x)
    ax1.set_xticklabels(domains)
    ax1.grid(True, axis="y")
    ax1.legend()

    for r in r1:
        h = r.get_height()
        ax1.annotate(f"{h:.1f}ms", (r.get_x() + r.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9, fontweight="bold", color=C_UNDEF)
    for r in r2:
        h = r.get_height()
        ax1.annotate(f"{h:.1f}ms", (r.get_x() + r.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9, fontweight="bold", color=C_DEF)

    # Panel 2: Recovery Phase Spillover
    r3 = ax2.bar(x - width/2, u_rec, width, label="Undefended", color=C_UNDEF, alpha=0.9, edgecolor="black")
    r4 = ax2.bar(x + width/2, d_rec, width, label="Defended (CB)", color=C_DEF, alpha=0.9, edgecolor="black")
    ax2.set_ylabel("Median Latency (ms)")
    ax2.set_title("Recovery Phase: Cascade Spillover vs. Isolation")
    ax2.set_xticks(x)
    ax2.set_xticklabels(domains)
    ax2.grid(True, axis="y")
    ax2.legend()

    for r in r3:
        h = r.get_height()
        ax2.annotate(f"{h:.1f}ms", (r.get_x() + r.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9, fontweight="bold", color=C_UNDEF)
    for r in r4:
        h = r.get_height()
        ax2.annotate(f"{h:.1f}ms", (r.get_x() + r.get_width()/2, h), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=9, fontweight="bold", color=C_DEF)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig6_multidomain_spillover.png")
    fig.savefig(FIG_DIR / "fig6_multidomain_spillover.pdf")
    plt.close(fig)
    print("Saved fig6_multidomain_spillover")


# ─────────────────────────────────────────────────────────────────────────────
# FIGURE 4: End-to-End Time-Series Timeline Comparison
# ─────────────────────────────────────────────────────────────────────────────
def plot_timeline_profile():
    fig, ax = plt.subplots(figsize=(13, 5.5))

    # Pick representative runs (e.g. Run 9 undefended vs Run 10 defended)
    r_undef = runs[8]  # Run 9
    r_def = runs[9]    # Run 10

    # Build synthetic time axis based on sample intervals
    # Baseline: 15 samples (0 to 30s)
    # Attack: ~27-30 samples (30 to 90s)
    # Recovery: ~30 samples (90 to 150s)
    def make_timeline(run_obj):
        t = []
        lat = []
        # Baseline
        s_base = run_obj["latency_ms"]["baseline"]["A"]["samples"]
        t.extend(np.linspace(0, 30, len(s_base)))
        lat.extend(s_base)
        
        # During
        s_dur = run_obj["latency_ms"]["during"]["A"]["samples"]
        t.extend(np.linspace(30.1, 90, len(s_dur)))
        lat.extend(s_dur)
        
        # Recovery
        s_rec = run_obj["latency_ms"]["recovery"]["A"]["samples"]
        t.extend(np.linspace(90.1, 150, len(s_rec)))
        lat.extend(s_rec)
        return np.array(t), np.array(lat)

    t_u, lat_u = make_timeline(r_undef)
    t_d, lat_d = make_timeline(r_def)

    # Plot lines
    ax.plot(t_u, lat_u, color=C_UNDEF, lw=2.2, label=f"Undefended (Run {r_undef['run_id']}) — Persistent Queue Saturated", marker="o", markersize=4)
    ax.plot(t_d, lat_d, color=C_DEF, lw=2.2, label=f"Defended (Run {r_def['run_id']}) — Circuit Breaker Mitigated", marker="s", markersize=4)

    # Phase shading
    ax.axvspan(0, 30, color="#E9ECEF", alpha=0.5, label="Phase 1: Baseline (30s)")
    ax.axvspan(30, 90, color="#F8D7DA", alpha=0.35, label="Phase 2: PacketIn Flood (60s)")
    ax.axvspan(90, 150, color="#D1E7DD", alpha=0.35, label="Phase 3: Recovery (60s)")

    # Annotation for Circuit Breaker trigger & mitigation
    # T_trigger ≈ 44s
    ax.axvline(44.2, color="#7209B7", linestyle=":", lw=2, label="Circuit Breaker Detection & Reboot (t=44.2s)")
    ax.annotate("CB DETECT & KILL (PID 50088)\nRate > 1500 pkt/s, CPU=99.9%\nTTM: 4.42s",
                xy=(44.2, 42), xytext=(48, 160),
                arrowprops=dict(arrowstyle="->", color="#7209B7", lw=1.5),
                bbox=dict(boxstyle="round,pad=0.4", fc="#F3E8FF", ec="#7209B7", lw=1.2),
                fontweight="bold", fontsize=9, color="#581C87")

    ax.annotate("Meter / Port Drop Installed (in_port=3)\nFlood Throttled, CPU < 1%",
                xy=(48.6, 7.0), xytext=(55, 60),
                arrowprops=dict(arrowstyle="->", color=C_DEF, lw=1.5),
                bbox=dict(boxstyle="round,pad=0.4", fc="#E6F4EA", ec=C_DEF, lw=1.2),
                fontweight="bold", fontsize=9, color="#137333")

    ax.annotate("Unmitigated Queue Backlog\nLatency > 250 ms in recovery",
                xy=(125, 260), xytext=(100, 310),
                arrowprops=dict(arrowstyle="->", color=C_UNDEF, lw=1.5),
                bbox=dict(boxstyle="round,pad=0.4", fc="#FCE8E6", ec=C_UNDEF, lw=1.2),
                fontweight="bold", fontsize=9, color="#C5221F")

    ax.set_xlabel("Experiment Timeline (seconds)")
    ax.set_ylabel("Domain-A REST Latency (ms)")
    ax.set_title("End-to-End Latency Timeline: Undefended vs. Defended Controller Dynamics")
    ax.set_xlim(0, 150)
    ax.set_ylim(-10, 360)
    ax.grid(True)
    ax.legend(loc="upper left", framealpha=0.9, fontsize=9)

    plt.tight_layout()
    fig.savefig(FIG_DIR / "fig7_attack_timeline_profile.png")
    fig.savefig(FIG_DIR / "fig7_attack_timeline_profile.pdf")
    plt.close(fig)
    print("Saved fig7_attack_timeline_profile")

if __name__ == "__main__":
    plot_latency_comparison()
    plot_probe_health()
    plot_multidomain_spillover()
    plot_timeline_profile()
    print("All figures generated successfully in results/figures/!")
