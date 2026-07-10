import type { Metadata, Viewport } from "next";
import "./globals.css";
import Nav from "@/components/nav";
import PwaClient from "@/components/pwa-client";

export const metadata: Metadata = {
  title: "OpenPartsFlow",
  description: "OpenPartsFlow mobile operations app",
  applicationName: "OpenPartsFlow",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    title: "OpenParts",
    statusBarStyle: "black-translucent"
  },
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" }
    ],
    apple: [{ url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" }]
  },
  formatDetection: {
    telephone: false
  }
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: "#111827"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <PwaClient />
        <div className="app-shell">
          <header className="app-header container">
            <div className="app-header-brand">
              <span className="app-header-title">OpenPartsFlow</span>
              <span className="app-header-badge">Pilot</span>
            </div>
          </header>
          <Nav />
          <main className="app-main container">{children}</main>
        </div>
      </body>
    </html>
  );
}
