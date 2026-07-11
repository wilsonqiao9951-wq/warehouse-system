"use client";

import { useRef, useState } from "react";

export function VoiceRecorder({ disabled, onRecorded }: {
  disabled?: boolean;
  onRecorded: (blob: Blob, durationSeconds: number) => Promise<void>;
}) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const startedAtRef = useRef(0);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const start = async () => {
    try {
      setError("");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const chunks: Blob[] = [];
      const recorder = new MediaRecorder(stream);
      recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        const duration = Math.max(1, (Date.now() - startedAtRef.current) / 1000);
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        setBusy(true);
        try { await onRecorded(blob, duration); }
        catch (e) { setError(e instanceof Error ? e.message : "Voice-note upload failed."); }
        finally { setBusy(false); }
      };
      recorderRef.current = recorder;
      startedAtRef.current = Date.now();
      recorder.start();
      setRecording(true);
    } catch {
      setError("Microphone permission is required to record a voice note.");
    }
  };

  const stop = () => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
  };

  return <div>
    <button type="button" onClick={recording ? stop : start} disabled={disabled || busy}>
      {busy ? "Uploading…" : recording ? "Stop and upload" : "Record voice note"}
    </button>
    {recording && <span className="muted" style={{ marginLeft: 10 }}>Recording…</span>}
    {error && <p className="notice notice-error">{error}</p>}
  </div>;
}
