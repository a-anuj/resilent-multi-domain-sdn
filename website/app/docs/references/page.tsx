import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "References",
  description: "Bibliographic references from the project presentation: OpenFlow, Ryu, Mininet, SDN security, traffic engineering.",
};

const REFS = [
  {
    group: "SDN and OpenFlow",
    items: [
      { num: 1, cite: "Open Networking Foundation (ONF). OpenFlow Switch Specification, Version 1.3.5. ONF TS-011. March 2015." },
      { num: 2, cite: "McKeown, N., Anderson, T., Balakrishnan, H., Parulkar, G., Peterson, L., Rexford, J., Shenker, S., and Turner, J. (2008). OpenFlow: Enabling Innovation in Campus Networks. ACM SIGCOMM Computer Communication Review, 38(2), 69–74." },
      { num: 3, cite: "Kreutz, D., Ramos, F. M. V., Veríssimo, P. E., Rothenberg, C. E., Azodolmolky, S., and Uhlig, S. (2015). Software-Defined Networking: A Comprehensive Survey. Proceedings of the IEEE, 103(1), 14–76." },
    ],
  },
  {
    group: "Multi-Domain and Multi-Controller SDN",
    items: [
      { num: 4, cite: "Berde, P., et al. (2014). ONOS: Towards an Open, Distributed SDN OS. Proceedings of the 3rd Workshop on Hot Topics in Software Defined Networking (HotSDN '14). ACM." },
      { num: 5, cite: "Levin, D., Wundsam, A., Heller, B., Handigol, N., and Feldmann, A. (2012). Logically Centralized? State Distribution Trade-offs in Software Defined Networks. Proceedings of HotSDN '12. ACM." },
    ],
  },
  {
    group: "Control-Plane Security and Attacks",
    items: [
      { num: 6, cite: "Shin, S., Xu, L., Hong, S., and Gu, G. (2015). Enhancing Network Security through Software Defined Networking (SDN). Proceedings of the 25th International Conference on Computer Communication and Networks (ICCCN). IEEE." },
      { num: 7, cite: "Kalkan, K., and Zeadally, S. (2018). Securing Internet of Things with Software Defined Networking. IEEE Communications Magazine, 56(9), 186–192." },
      { num: 8, cite: "Scott-Hayward, S., O'Callaghan, G., and Sezer, S. (2013). SDN Security: A Survey. Proceedings of IEEE SDN for Future Networks and Services (SDN4FNS). IEEE." },
    ],
  },
  {
    group: "Traffic Engineering",
    items: [
      { num: 9, cite: "Wang, R., Butnariu, D., and Rexford, J. (2011). OpenFlow-Based Server Load Balancing Gone Wild. Proceedings of the 11th USENIX Workshop on Hot Topics in Management of Internet, Cloud, and Enterprise Networks and Services." },
      { num: 10, cite: "Agarwal, S., Kodialam, M., and Lakshman, T. V. (2013). Traffic Engineering in Software Defined Networks. Proceedings of IEEE INFOCOM 2013." },
    ],
  },
  {
    group: "Ryu SDN Framework",
    items: [
      { num: 11, cite: "Ryu SDN Framework. Ryu Documentation.", url: "https://ryu.readthedocs.io/" },
      { num: 12, cite: "Nippon Telegraph and Telephone Corporation (NTT). Ryu: Component-Based Software Defined Networking Framework.", url: "https://github.com/faucetsdn/ryu" },
    ],
  },
  {
    group: "Mininet",
    items: [
      { num: 13, cite: "Lantz, B., Heller, B., and McKeown, N. (2010). A Network in a Laptop: Rapid Prototyping for Software-Defined Networks. Proceedings of the 9th ACM SIGCOMM Workshop on Hot Topics in Networks (Hotnets-IX)." },
      { num: 14, cite: "Mininet Project. Mininet: An Instant Virtual Network on your Laptop.", url: "http://mininet.org/" },
    ],
  },
  {
    group: "Circuit Breakers and Resilience Patterns",
    items: [
      { num: 15, cite: "Nygard, M. T. (2007). Release It! Design and Deploy Production-Ready Software. Pragmatic Bookshelf. (Original circuit breaker pattern description)" },
    ],
  },
];

export default function ReferencesPage() {
  return (
    <div className="docs-layout">
      <aside className="docs-sidebar" aria-label="Page sections">
        <div className="sidebar-nav-title">On This Page</div>
        <ul className="sidebar-nav-list">
          {REFS.map((g) => (
            <li key={g.group} className="sidebar-nav-item">
              <a href={`#${g.group.toLowerCase().replace(/[^a-z]+/g, "-")}`}>{g.group}</a>
            </li>
          ))}
        </ul>
      </aside>

      <article className="docs-article" aria-labelledby="ref-title">
        <div style={{ marginBottom: "2rem" }}>
          <p className="section-eyebrow">Documentation</p>
          <h1 id="ref-title">References</h1>
          <p style={{ fontSize: "1.05rem", color: "var(--text-secondary)", marginTop: "0.75rem" }}>
            Bibliographic references reproduced from the project presentation.
            The presentation is the authoritative source. No fabricated citations are added.
          </p>
        </div>

        {REFS.map((group) => (
          <section
            key={group.group}
            id={group.group.toLowerCase().replace(/[^a-z]+/g, "-")}
            aria-labelledby={`ref-${group.group.toLowerCase().replace(/[^a-z]+/g, "-")}`}
          >
            <h2 id={`ref-${group.group.toLowerCase().replace(/[^a-z]+/g, "-")}`}>
              {group.group}
            </h2>
            <ol start={group.items[0].num} style={{ paddingLeft: "1.5rem", color: "var(--text-secondary)" }}>
              {group.items.map((ref) => (
                <li key={ref.num} style={{ marginBottom: "0.75rem", fontSize: "0.9rem", lineHeight: 1.7 }}>
                  {ref.cite}
                  {ref.url && (
                    <>
                      {" "}
                      <a href={ref.url} target="_blank" rel="noopener noreferrer">
                        {ref.url}
                      </a>
                    </>
                  )}
                </li>
              ))}
            </ol>
          </section>
        ))}

        <div className="callout info" style={{ marginTop: "2rem" }}>
          <div className="callout-title">Note</div>
          <p>
            All references are reproduced from the project presentation. The presentation
            should be consulted as the authoritative source. No citations have been added
            beyond those present in the source material.
          </p>
        </div>

        <div style={{ marginTop: "2rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <Link href="/docs" className="btn btn-primary">All Documentation →</Link>
          <Link href="/docs/contributions" className="btn btn-secondary">Novel Contributions →</Link>
        </div>
      </article>
    </div>
  );
}
