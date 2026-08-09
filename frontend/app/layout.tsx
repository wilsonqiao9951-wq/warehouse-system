import type { Metadata, Viewport } from "next";
import "./globals.css";
import Nav from "@/components/nav";
import PwaClient from "@/components/pwa-client";
import BrandHeader from "@/components/brand-header";
import { AccessSessionProvider } from "@/components/access-session-provider";
import RouteAccessGuard from "@/components/route-access-guard";

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
        <AccessSessionProvider>
          <div className="app-shell">
            <BrandHeader />
            <Nav />
            <main className="app-main container">
              <RouteAccessGuard>{children}</RouteAccessGuard>
            </main>
          </div>
        </AccessSessionProvider>
      </body>
    </html>
  );
}
