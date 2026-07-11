"use client";

import { useEffect, useState } from "react";

type DeferredPromptEvent = Event & {
  prompt: () => Promise<void>;
};

export default function PwaClient() {
  const [canInstall, setCanInstall] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState<DeferredPromptEvent | null>(null);
  const [offline, setOffline] = useState(false);
  const [iosInstallHint, setIosInstallHint] = useState(false);

  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }

    const handleBeforeInstall = (event: Event) => {
      event.preventDefault();
      setDeferredPrompt(event as DeferredPromptEvent);
      setCanInstall(true);
    };

    const onOnline = () => setOffline(false);
    const onOffline = () => setOffline(true);
    setOffline(!navigator.onLine);
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !("standalone" in window.navigator && (window.navigator as Navigator & { standalone?: boolean }).standalone);
    setIosInstallHint(ios);

    window.addEventListener("beforeinstallprompt", handleBeforeInstall);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);

    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstall);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, []);

  const triggerInstall = async () => {
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    setDeferredPrompt(null);
    setCanInstall(false);
  };

  return (
    <>
      {offline && (
        <div className="offline-banner" role="status">
          You are offline. Cached pages may open, but saving data requires a connection.
        </div>
      )}
      {canInstall && (
        <button type="button" className="install-btn" onClick={triggerInstall}>
          Install app
        </button>
      )}
      {iosInstallHint && !offline && (
        <div className="install-hint" role="status">Install OpenPartsFlow: tap Share, then “Add to Home Screen”.</div>
      )}
    </>
  );
}
