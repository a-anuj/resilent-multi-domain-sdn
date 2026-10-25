import Link from "next/link";

const FOOTER_LINKS = [
  { href: "/", label: "Overview" },
  { href: "/architecture", label: "Architecture" },
  { href: "/methodology", label: "Methodology" },
  { href: "/results", label: "Results" },
  { href: "/docs", label: "Documentation" },
  { href: "https://github.com/a-anuj/resilent-multi-domain-sdn", label: "GitHub Repository", external: true },
];

export function SiteFooter() {
  return (
    <footer className="site-footer" role="contentinfo">
      <div className="container">
        <div className="footer-inner">
          <div>
            <div className="footer-brand">Resilient Multi-Domain SDN</div>
            <p className="footer-desc">
              Research documentation for an automated circuit breaker system defending
              multi-controller SDN control planes against PacketIn saturation attacks.
            </p>
          </div>
          <nav className="footer-links" aria-label="Footer navigation">
            {FOOTER_LINKS.map((link) =>
              link.external ? (
                <a
                  key={link.href}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={`${link.label} (opens in new tab)`}
                >
                  {link.label} ↗
                </a>
              ) : (
                <Link key={link.href} href={link.href}>
                  {link.label}
                </Link>
              )
            )}
          </nav>
        </div>
        <div className="footer-caveat">
          <strong>Evidence caveat:</strong> All experimental results reported on this site
          are preliminary measurements from a single-instance Mininet software testbed.
          Results should not be generalized without broader evaluation including repeated
          trials, statistical confidence intervals, varied topologies, and hardware validation.
          No personal, author, or institutional identifiers are published on this site.
        </div>
      </div>
    </footer>
  );
}
