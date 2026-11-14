"use client";

import { memo, useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_URL } from "@/lib/api";
import type { VoiceAlert } from "@/lib/contracts";

const AUDIO_LEAD_IN_S = 0.5;

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
  const enabledRef = useRef(false);
  const queueRef = useRef<VoiceAlert[]>([]);
  const playingRef = useRef(false);
  const playbackGenerationRef = useRef(0);
  const audioContextRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const alertIds = alerts.map((alert) => alert.event_id).join("|");

  const stopPlayback = useCallback(() => {
    playbackGenerationRef.current += 1;
    queueRef.current = [];
    requestRef.current?.abort();
    if (sourceRef.current) {
      try { sourceRef.current.stop(); } catch { /* already stopped */ }
    }
    sourceRef.current = null;
    requestRef.current = null;
    playingRef.current = false;
  }, []);

  const playNext = useCallback(function playNext() {
    if (!enabledRef.current || playingRef.current || queueRef.current.length === 0) return;
    const selected = queueRef.current.shift()!;
    const generation = playbackGenerationRef.current;
    playingRef.current = true;
    const controller = new AbortController();
    requestRef.current = controller;
    setVoiceError(null);
    void (async () => {
      let source: AudioBufferSourceNode | null = null;
      try {
        const response = await fetch(`${BACKEND_URL}/api/voice/alerts/${encodeURIComponent(selected.event_id)}/audio`, {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error(response.status === 503 ? "ElevenLabs voice is unavailable; alerts remain visible." : "Voice playback failed.");
        const encoded = await response.arrayBuffer();
        if (controller.signal.aborted || generation !== playbackGenerationRef.current) return;
        const context = audioContextRef.current;
        if (!context || context.state === "closed") return;
        const decoded = await context.decodeAudioData(encoded);
        if (controller.signal.aborted || generation !== playbackGenerationRef.current) return;
        const leadInFrames = Math.ceil(decoded.sampleRate * AUDIO_LEAD_IN_S);
        const padded = context.createBuffer(decoded.numberOfChannels, leadInFrames + decoded.length, decoded.sampleRate);
        for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) {
          padded.getChannelData(channel).set(decoded.getChannelData(channel), leadInFrames);
        }
        source = context.createBufferSource();
        source.buffer = padded;
        source.connect(context.destination);
        sourceRef.current = source;
        await new Promise<void>((resolve, reject) => {
          source!.onended = () => resolve();
          try { source!.start(); } catch (error) { reject(error); }
        });
      } catch (error) {
        if (!controller.signal.aborted && generation === playbackGenerationRef.current) {
          setVoiceError(error instanceof Error ? error.message : "Voice playback failed.");
        }
      } finally {
        source?.disconnect();
        if (generation === playbackGenerationRef.current) {
          if (sourceRef.current === source) sourceRef.current = null;
          if (requestRef.current === controller) requestRef.current = null;
          playingRef.current = false;
          playNext();
        }
      }
    })();
  }, []);

  useEffect(() => {
    if (runRef.current !== runId) {
      runRef.current = runId;
      seenRef.current.clear();
      stopPlayback();
    }
    const fresh = alerts.filter((alert) => !seenRef.current.has(alert.event_id));
    for (const alert of fresh) seenRef.current.add(alert.event_id);
    if (!enabled || fresh.length === 0 || !runId) return;
    const timely = fresh.filter((alert) => simulationTime == null || simulationTime - alert.simulation_time_s <= 8);
    queueRef.current.push(...timely);
    queueRef.current.sort((a, b) => rank(b) - rank(a) || a.simulation_time_s - b.simulation_time_s);
    playNext();
  }, [alertIds, alerts, enabled, runId, simulationTime, playNext, stopPlayback]);

  useEffect(() => () => {
    stopPlayback();
    void audioContextRef.current?.close();
    audioContextRef.current = null;
  }, [stopPlayback]);

  const toggleVoice = () => {
    if (enabled) {
      enabledRef.current = false;
      stopPlayback();
      void audioContextRef.current?.close();
      audioContextRef.current = null;
      setEnabled(false);
      return;
    }
    for (const alert of alerts) seenRef.current.add(alert.event_id);
    setVoiceError(null);
    audioContextRef.current = new AudioContext();
    void audioContextRef.current.resume().catch(() => setVoiceError("Voice playback failed."));
    enabledRef.current = true;
    setEnabled(true);
  };

  return (
    <div className="surface rounded-[14px] p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono text-[10px] uppercase tracking-[.2em] text-[#ae9785]">Traffic alerts</p>
          <h2 className="mt-1 text-sm font-medium">Voice updates</h2>
        </div>
        <button type="button" aria-pressed={enabled} onClick={toggleVoice} className="rounded-lg border border-white/15 px-2.5 py-1.5 text-[11px] text-[#f5e2d3] hover:border-[#70e9a6]/50">
          {enabled ? "Mute" : "Enable voice"}
        </button>
      </div>
      <p className="mt-3 text-[10px] leading-relaxed text-[#b69b87]">Only traffic events trigger speech. Captions remain available when audio is off.</p>
      {voiceError && <p role="status" className="mt-3 text-[11px] text-[#f0bc55]">{voiceError}</p>}
      <div aria-live="polite" className="mt-3 space-y-2">
        {alerts.length === 0 ? <p className="text-xs text-[#b69b87]">No traffic alerts yet.</p> : alerts.slice(-3).reverse().map((alert) => (
          <div key={alert.event_id} className="rounded-lg border border-white/[.06] bg-white/[.025] px-3 py-2">
            <p className={`text-[10px] uppercase tracking-wide ${alert.priority === "emergency" ? "text-[#ff9278]" : "text-[#70e9a6]"}`}>{alert.message_id.replaceAll(".", " ")}</p>
            <p className="mt-1 text-xs leading-relaxed text-[#f5e2d3]">{alert.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}, (previous, next) => previous.runId === next.runId
  && previous.alerts.length === next.alerts.length
  && previous.alerts.every((alert, index) => alert.event_id === next.alerts[index].event_id));
