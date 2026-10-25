import type { Metadata } from "next";
import { Space_Grotesk, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { SiteHeader } from "@/components/SiteHeader";
import { SiteFooter } from "@/components/SiteFooter";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Resilient Multi-Domain SDN",
    template: "%s | Resilient Multi-Domain SDN",
  },
  description:
    "Research documentation for Resilient Multi-Domain SDN: Automated Circuit Breaker for Control-Plane Saturation Defense. A multi-controller SDN testbed with congestion-aware traffic engineering and automated defense against PacketIn flood attacks.",
  keywords: [
    "SDN",
    "Software-Defined Networking",
    "circuit breaker",
    "control plane",
    "Ryu",
    "Mininet",
    "OpenFlow",
    "traffic engineering",
    "multi-domain",
    "network security",
  ],
  openGraph: {
    title: "Resilient Multi-Domain SDN",
    description:
      "Automated Circuit Breaker for Control-Plane Saturation Defense in Multi-Domain SDN.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${spaceGrotesk.variable} ${inter.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        <SiteHeader />
        <main id="main-content">{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
