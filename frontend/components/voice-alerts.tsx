"use client";

import { memo, useEffect, useRef, useState } from "react";
import { BACKEND_URL } from "@/lib/api";
import type { VoiceAlert } from "@/lib/contracts";

function rank(alert: VoiceAlert): number {
  if (alert.message_id === "emergency.requested" || alert.message_id === "emergency.already_green") return 3;
  if (alert.message_id === "emergency.green_confirmed") return 2;
  if (alert.priority === "emergency") return 1;
  return 0;
}

export const VoiceAlerts = memo(function VoiceAlerts({ alerts, runId, simulationTime }: { alerts: VoiceAlert[]; runId: string | null; simulationTime: number | null }) {
  const [enabled, setEnabled] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const seenRef = useRef(new Set<string>());
  const runRef = useRef<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const playingPriorityRef = useRef<VoiceAlert["priority"] | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const alertIds = alerts.map((alert) => alert.event_id).join("|");

  useEffect(() => {
    if (runRef.current !== runId) {
      runRef.current = runId;
      seenRef.current.clear();
      requestRef.current?.abort();
      audioRef.current?.pause();
      audioRef.current = null;
      playingPriorityRef.current = null;
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
    const fresh = alerts.filter((alert) => !seenRef.current.has(alert.event_id));
    for (const alert of fresh) seenRef.current.add(alert.event_id);
    if (!enabled || fresh.length === 0 || !runId) return;
    const timely = fresh.filter((alert) => simulationTime == null || simulationTime - alert.simulation_time_s <= 8);
    if (timely.length === 0) return;
    const selected = timely.sort((a, b) => rank(b) - rank(a))[0];
    if (playingPriorityRef.current === "emergency" && selected.priority === "routine") return;
    const controller = new AbortController();
    requestRef.current?.abort();
    requestRef.current = controller;
    audioRef.current?.pause();
    playingPriorityRef.current = selected.priority;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = null;
    setVoiceError(null);
    void (async () => {
      let objectUrl: string | null = null;
      try {
        const response = await fetch(`${BACKEND_URL}/api/voice/alerts/${encodeURIComponent(selected.event_id)}/audio`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error(response.status === 503 ? "ElevenLabs voice is unavailable; alerts remain visible." : "Voice playback failed.");
        objectUrl = URL.createObjectURL(await response.blob());
        if (controller.signal.aborted) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        objectUrlRef.current = objectUrl;
        const audio = new Audio(objectUrl);
        audioRef.current = audio;
        audio.onended = () => {
          if (audioRef.current === audio) playingPriorityRef.current = null;
          if (objectUrlRef.current === objectUrl) objectUrlRef.current = null;
          if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
        await audio.play();
      } catch (error) {
        if (requestRef.current === controller) playingPriorityRef.current = null;
        if (!controller.signal.aborted) setVoiceError(error instanceof Error ? error.message : "Voice playback failed.");
        if (objectUrl) {
          if (objectUrlRef.current === objectUrl) objectUrlRef.current = null;
          URL.revokeObjectURL(objectUrl);
        }
      }
    })();
    return () => controller.abort();
  }, [alertIds, alerts, enabled, runId, simulationTime]);

  useEffect(() => () => {
    requestRef.current?.abort();
    audioRef.current?.pause();
    playingPriorityRef.current = null;
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);

  const toggleVoice = () => {
    if (enabled) {
      requestRef.current?.abort();
      audioRef.current?.pause();
      audioRef.current = null;
      playingPriorityRef.current = null;
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
      setEnabled(false);
      return;
    }
    for (const alert of alerts) seenRef.current.add(alert.event_id);
    setVoiceError(null);
    setEnabled(true);
  };

  return (
    <div className="rounded-[20px] border border-white/[.07] bg-[#10171c] p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#667781]">Traffic alerts</p>
          <h2 className="mt-1 text-sm font-medium">Voice updates</h2>
        </div>
        <button type="button" aria-pressed={enabled} onClick={toggleVoice} className="rounded-lg border border-white/15 px-2.5 py-1.5 text-[11px] text-[#d7e1e6] hover:border-[#70e9a6]/50">
          {enabled ? "Mute" : "Enable voice"}
        </button>
      </div>
      <p className="mt-3 text-[10px] leading-relaxed text-[#71818a]">Only traffic events trigger speech. Captions remain available when audio is off.</p>
      {voiceError && <p role="status" className="mt-3 text-[11px] text-[#f0bc55]">{voiceError}</p>}
      <div aria-live="polite" className="mt-3 space-y-2">
        {alerts.length === 0 ? <p className="text-xs text-[#71818a]">No traffic alerts yet.</p> : alerts.slice(-3).reverse().map((alert) => (
          <div key={alert.event_id} className="rounded-lg border border-white/[.06] bg-white/[.025] px-3 py-2">
            <p className={`text-[10px] uppercase tracking-wide ${alert.priority === "emergency" ? "text-[#ff9278]" : "text-[#70e9a6]"}`}>{alert.message_id.replaceAll(".", " ")}</p>
            <p className="mt-1 text-xs leading-relaxed text-[#d7e1e6]">{alert.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}, (previous, next) => previous.runId === next.runId
  && previous.alerts.length === next.alerts.length
  && previous.alerts.every((alert, index) => alert.event_id === next.alerts[index].event_id));
