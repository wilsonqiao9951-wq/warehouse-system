"use client";

import { useEffect, useState } from "react";
import { getOfflineQueue, syncOfflineQueue } from "@/lib/api";

type DeferredPromptEvent = Event & {
  prompt: () => Promise<void>;
};

export default function PwaClient() {
  const [canInstall, setCanInstall] = useState(false);
  const [deferredPrompt, setDeferredPrompt] = useState<DeferredPromptEvent | null>(null);
  const [offline, setOffline] = useState(false);
  const [iosInstallHint, setIosInstallHint] = useState(false);
  const [queued, setQueued] = useState(0);

  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }

    const handleBeforeInstall = (event: Event) => {
      event.preventDefault();
      setDeferredPrompt(event as DeferredPromptEvent);
      setCanInstall(true);
    };

    const updateQueue = () => setQueued(getOfflineQueue().length);
    const onOnline = () => { setOffline(false); void syncOfflineQueue().then(updateQueue); };
    const onOffline = () => setOffline(true);
    setOffline(!navigator.onLine);
    const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !("standalone" in window.navigator && (window.navigator as Navigator & { standalone?: boolean }).standalone);
    setIosInstallHint(ios);
    updateQueue();

    window.addEventListener("beforeinstallprompt", handleBeforeInstall);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("opf-offline-queued", updateQueue);

    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstall);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("opf-offline-queued", updateQueue);
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
      {!offline && queued > 0 && <div className="sync-banner" role="status">Syncing {queued} offline change{queued === 1 ? "" : "s"}…</div>}
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
