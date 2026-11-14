"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_URL } from "@/lib/api";
import type { VoiceAlert } from "@/lib/contracts";
import { groupAlertsForPlayback, PlaybackGate } from "@/lib/voice-alert-coordinator";

const AGGREGATION_WINDOW_MS = 650;
const MAX_ALERT_AGE_S = 8;
const PLAYBACK_TIMEOUT_GRACE_MS = 5000;
const VOICE_PREFERENCE_KEY = "flowgency.voice-alerts.enabled.v1";

interface QueueItem { alerts: VoiceAlert[] }

export const VoiceAlerts = memo(function VoiceAlerts({ alerts, runId, simulationTime }: { alerts: VoiceAlert[]; runId: string | null; simulationTime: number | null }) {
  const [enabled, setEnabled] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const seenRef = useRef(new Set<string>());
  const runRef = useRef<string | null>(null);
  const enabledRef = useRef(false);
  const queueRef = useRef<QueueItem[]>([]);
  const aggregationRef = useRef<VoiceAlert[]>([]);
  const aggregationTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playbackGateRef = useRef(new PlaybackGate());
  const playbackGenerationRef = useRef(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const alertIds = alerts.map((alert) => alert.event_id).join("|");

  const stopPlayback = useCallback(() => {
    playbackGenerationRef.current += 1;
    queueRef.current = [];
    aggregationRef.current = [];
    if (aggregationTimerRef.current) clearTimeout(aggregationTimerRef.current);
    aggregationTimerRef.current = null;
    requestRef.current?.abort();
    if (sourceRef.current) {
      try { sourceRef.current.stop(); } catch { /* already stopped */ }
    }
    sourceRef.current = null;
    requestRef.current = null;
    playbackGateRef.current.reset();
  }, []);

  const playNext = useCallback(function playNext() {
    if (!enabledRef.current || queueRef.current.length === 0 || !playbackGateRef.current.begin()) return;
    const selected = queueRef.current.shift()!;
    const generation = playbackGenerationRef.current;
    const controller = new AbortController();
    requestRef.current = controller;
    const fetchTimeout = setTimeout(() => controller.abort(), 15000);
    setVoiceError(null);
    void (async () => {
      let source: AudioBufferSourceNode | null = null;
      try {
        const query = selected.alerts.map((alert) => `event_ids=${encodeURIComponent(alert.event_id)}`).join("&");
        const response = await fetch(`${BACKEND_URL}/api/voice/audio?${query}`, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw new Error(response.status === 503 ? "Voice alerts unavailable" : "Voice playback failed");
        const encoded = await response.arrayBuffer();
        if (controller.signal.aborted || generation !== playbackGenerationRef.current) return;
        const context = audioContextRef.current;
        if (!context || context.state !== "running") throw new Error("Browser blocked audio playback");
        const decoded = await context.decodeAudioData(encoded);
        if (generation !== playbackGenerationRef.current) return;
        source = context.createBufferSource();
        source.buffer = decoded;
        source.connect(context.destination);
        sourceRef.current = source;
        await new Promise<void>((resolve, reject) => {
          const timeout = setTimeout(() => {
            try { source?.stop(); } catch { /* already stopped */ }
            reject(new Error("Voice playback timed out"));
          }, decoded.duration * 1000 + PLAYBACK_TIMEOUT_GRACE_MS);
          source!.onended = () => { clearTimeout(timeout); resolve(); };
          try { source!.start(); } catch (error) { clearTimeout(timeout); reject(error); }
        });
      } catch (error) {
        if (!controller.signal.aborted && generation === playbackGenerationRef.current) setVoiceError(error instanceof Error ? error.message : "Voice playback failed");
      } finally {
        clearTimeout(fetchTimeout);
        source?.disconnect();
        if (generation === playbackGenerationRef.current) {
          if (sourceRef.current === source) sourceRef.current = null;
          if (requestRef.current === controller) requestRef.current = null;
          playbackGateRef.current.end();
          playNext();
        }
      }
    })();
  }, []);

  const flushAggregation = useCallback(() => {
    aggregationTimerRef.current = null;
    const buffered = aggregationRef.current;
    aggregationRef.current = [];
    if (!enabledRef.current || buffered.length === 0) return;
    for (const group of groupAlertsForPlayback(buffered)) queueRef.current.push({ alerts: group });
    playNext();
  }, [playNext]);

  useEffect(() => {
    if (runRef.current !== runId) {
      runRef.current = runId;
      seenRef.current.clear();
      stopPlayback();
    }
    const fresh = alerts.filter((alert) => !seenRef.current.has(alert.event_id));
    for (const alert of fresh) seenRef.current.add(alert.event_id);
    if (!enabled || fresh.length === 0 || !runId) return;
    const timely = fresh.filter((alert) => simulationTime == null || simulationTime - alert.simulation_time_s <= MAX_ALERT_AGE_S);
    aggregationRef.current.push(...timely);
    if (timely.length > 0 && aggregationTimerRef.current === null) aggregationTimerRef.current = setTimeout(flushAggregation, AGGREGATION_WINDOW_MS);
  }, [alertIds, alerts, enabled, flushAggregation, runId, simulationTime, stopPlayback]);

  useEffect(() => () => {
    stopPlayback();
    void audioContextRef.current?.close();
    audioContextRef.current = null;
  }, [stopPlayback]);

  const toggleVoice = async () => {
    if (enabled) {
      enabledRef.current = false;
      stopPlayback();
      void audioContextRef.current?.close();
      audioContextRef.current = null;
      setEnabled(false);
      try { localStorage.setItem(VOICE_PREFERENCE_KEY, "muted"); } catch { /* optional */ }
      return;
    }
    for (const alert of alerts) seenRef.current.add(alert.event_id);
    setVoiceError(null);
    const context = new AudioContext();
    audioContextRef.current = context;
    try {
      await context.resume();
      if (context.state !== "running") throw new Error("Browser blocked audio playback");
      enabledRef.current = true;
      setEnabled(true);
      try { localStorage.setItem(VOICE_PREFERENCE_KEY, "enabled"); } catch { /* optional */ }
    } catch {
      enabledRef.current = false;
      setEnabled(false);
      setVoiceError("Voice alerts unavailable: browser autoplay is blocked");
      await context.close();
      audioContextRef.current = null;
    }
  };

  return (
    <div className="surface rounded-[14px] p-4">
      <div className="flex items-start justify-between gap-2"><div><p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#ae9785]">Traffic alerts</p><h2 className="mt-1 text-sm font-medium">Voice Alert Coordinator</h2></div><button type="button" aria-pressed={enabled} onClick={() => void toggleVoice()} className="rounded-lg border border-white/15 px-2.5 py-1.5 text-[11px] text-[#f5e2d3] hover:border-[#70e9a6]/50">{enabled ? "Mute" : "Enable Voice Alerts"}</button></div>
      <p role="status" className={`mt-3 text-[11px] ${voiceError ? "text-[#f0bc55]" : enabled ? "text-[#70e9a6]" : "text-[#b69b87]"}`}>{voiceError ?? (enabled ? "Voice alerts enabled" : "Voice alerts muted")}</p>
      <p className="mt-2 text-[10px] leading-relaxed text-[#b69b87]">One global FIFO player · {AGGREGATION_WINDOW_MS} ms aggregation · stale alerts discarded.</p>
      <div aria-live="polite" className="mt-3 space-y-2">{alerts.length === 0 ? <p className="text-xs text-[#b69b87]">No traffic alerts yet.</p> : alerts.slice(-3).reverse().map((alert) => <div key={alert.event_id} className="rounded-lg border border-white/[.06] bg-white/[.025] px-3 py-2"><p className={`text-[10px] uppercase tracking-wide ${alert.priority === "emergency" ? "text-[#ff9278]" : "text-[#70e9a6]"}`}>{alert.message_id.replaceAll(".", " ")}</p><p className="mt-1 text-xs leading-relaxed text-[#f5e2d3]">{alert.text}</p></div>)}</div>
    </div>
  );
}, (previous, next) => previous.runId === next.runId
  && previous.simulationTime === next.simulationTime
  && previous.alerts.length === next.alerts.length
  && previous.alerts.every((alert, index) => alert.event_id === next.alerts[index].event_id));
