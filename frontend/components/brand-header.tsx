"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api, hasStoredAuthentication } from "@/lib/api";
import { OrganizationBranding } from "@/types";

const DEFAULT_BRAND: OrganizationBranding = {
  name: "OpenPartsFlow",
  slug: "openpartsflow",
  brand_logo_url: null,
  brand_primary_color: "#155eef",
  brand_login_headline: null
};

export default function BrandHeader() {
  const pathname = usePathname();
  const [branding, setBranding] = useState<OrganizationBranding>(DEFAULT_BRAND);
  const [plan, setPlan] = useState("");

  const load = useCallback(async () => {
    const requestedSlug = new URLSearchParams(window.location.search).get("organization");
    if (hasStoredAuthentication()) {
      try {
        const settings = await api.getOrganizationSettings();
        setBranding(settings);
        setPlan(settings.plan_code);
        return;
      } catch {
        // A branded login link can still render when a prior token is expired,
        // revoked, or belongs to a suspended subscription.
      }
    }
    if (requestedSlug) {
      try {
        const publicBranding = await api.getPublicOrganizationBranding(requestedSlug);
        setBranding(publicBranding);
        setPlan("");
        return;
      } catch {
        // Unknown or inactive slugs use the neutral platform identity.
      }
    }
    setBranding(DEFAULT_BRAND);
    setPlan("");
  }, []);

  useEffect(() => {
    void load();
    window.addEventListener("opf-organization-branding", load);
    return () => window.removeEventListener("opf-organization-branding", load);
  }, [load, pathname]);

  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--accent", branding.brand_primary_color);
    root.style.setProperty("--header-bar", branding.brand_primary_color);
    return () => {
      root.style.setProperty("--accent", DEFAULT_BRAND.brand_primary_color);
      root.style.setProperty("--header-bar", DEFAULT_BRAND.brand_primary_color);
    };
  }, [branding.brand_primary_color]);

  return (
    <header className="app-header container">
      <div className="app-header-brand">
        {branding.brand_logo_url && (
          <span
            aria-label={`${branding.name} logo`}
            role="img"
            className="app-header-logo"
            style={{ backgroundImage: `url("${branding.brand_logo_url}")` }}
          />
        )}
        <span className="app-header-title">{branding.name}</span>
        <span className="app-header-badge">
          {plan ? `${plan[0].toUpperCase()}${plan.slice(1)}` : "Customer portal"}
        </span>
      </div>
    </header>
  );
}
