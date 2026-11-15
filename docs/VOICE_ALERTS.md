# Voice alerts for the simulation demo

## Purpose and current status

Flowgency now derives bounded traffic alerts from simulation snapshots and
offers optional ElevenLabs playback in the browser. Spoken audio needs
`ELEVENLABS_API_KEY` and `ELEVENLABS_VOICE_ID` in the backend process environment.
Without them, the captions still work. Alerts never change traffic control.

Voice announcements concern traffic conditions and confirmed signal behavior
only. Selecting a scenario or control mode, pressing Start/Pause/Resume/Reset,
connecting the browser, and finishing a run do not produce speech. Enabling or
muting audio also produces no spoken confirmation.

ElevenLabs is the text-to-speech renderer. It does not decide when a signal
changes or when an alert is valid. The authoritative SUMO worker produces state;
a separate announcement policy recognizes meaningful state transitions; the
browser displays the text and, if the operator enabled sound, plays the audio.
Voice must never block a SUMO step or influence the signal controller.

Adaptive cycle-plan changes do not trigger speech. Congestion alerts are implemented but disabled until a scenario-specific threshold is configured and validated. Emergency announcements use declared SUMO emergency types in both networks, not camera or YOLO detections. Do not announce an ambulance from camera data until that integration is present and its source is explicit. Fixed Timing and Adaptive Network announce detection only; priority activation is announced only for `adaptive_emergency_priority`.

## Spoken message catalog

The English copy matches the current UI. Set `FLOWGENCY_VOICE_LANGUAGE=ro` in
the backend environment for Romanian captions and speech. Keep the message ID
and trigger independent of language.
These short phrases can be generated on demand and cached by language, voice,
model, and exact text.

| ID | Trigger | English | Romanian |
| --- | --- | --- | --- |
| `traffic.congestion_sustained` | A measured, deduplicated controlled-lane queue stays above a calibrated threshold for a configured number of simulation seconds. Do not enable until that threshold is set for the scenario. | "Traffic is building near the intersection." | „Traficul se aglomerează în apropierea intersecției.” |
| `emergency.detected` | An emergency event for a vehicle/intersection is first observed. Available in Fixed Timing, Adaptive Network, and Adaptive Network + Emergency Priority. | "Emergency vehicle detected at intersection 1." | „Vehicul de intervenție detectat la intersecția 1.” |
| `emergency.priority_activated` | That event enters `priority_active`. Produced only when emergency priority is supported/enabled. It can mean a compatible green is held or safe clearance is requested; it does not assert green is already present. | "Emergency priority activated at intersection 1." | „Prioritate de urgență activată la intersecția 1.” |
| `emergency.priority_completed` | An event directly transitions from `priority_active` to `completed`, or disappears while active. This ends the event, not proof of safe passage or restored normal timing. | "Emergency priority completed at intersection 1." | „Prioritate de urgență încheiată la intersecția 1.” |

All current application scenarios provide `emergency_events` and use the three
emergency messages above. The old `emergency.requested`, `emergency.already_green`,
and `emergency.green_confirmed` phrases remain only as compatibility behavior for
snapshots that do not contain an event list. Do not describe them as the current
normal application flow. In particular, the current event flow does emit a
priority-completed announcement; it is different from the removed legacy
`emergency.request_ended` message.

### London intersection names

London captions and speech use `intersection 1`, `intersection 2`, etc. Numbers
come from the sorted full `traffic_light_controllers` inventory in the first
snapshot, before emergencies arrive. The same network gets the same numbers in
Normal/Rush Hour/Unbalanced and all controller modes. Later unknown controllers
append without renumbering earlier announcements. This is a presentation alias,
not a rename in SUMO or a geographic/JamCam label. Raw `intersection_id` values
remain unchanged in alert/event metadata, control decisions, and technical views.
Reset clears history and rebuilds the same numbering for the same inventory.
Legacy London events whose IDs start with `GS_` can also receive aliases when the
network selector is absent; full inventory is required for cross-run numbering.

Aggregation uses these same aliases, e.g. "Emergency vehicles detected at
intersections 1 and 2." Multiple vehicles at one intersection use a single number.
Romanian aggregation is localized too. Each physical SUMO controller is numbered;
these are not the five selected camera-site labels J1–J5.

Avoid saying that an emergency vehicle **passed safely**, that normal timing
**resumed**, or that traffic **improved** unless the corresponding outcome has
been measured.

## Text-only status, not spoken by default

| State | Display copy | Why it is not spoken |
| --- | --- | --- |
| `minimum_green_protected_before_emergency` | "Waiting for the current minimum green." | May repeat on each simulation step. |
| Yellow or all-red actually entered after a conflicting request | "Safe signal clearance in progress." | Short transition; speech may finish after it. |
| Additional emergency vehicle is queued | "Another emergency request is waiting." | Avoid overlapping or misleading announcements. |
| Adaptive cycle-plan change | Show timing data in the simulation UI. | Recalculation alone does not prove that traffic improved. |
| ElevenLabs unavailable or sound disabled | Show the same alert text in the UI. | Audio is optional; simulation continues. |

## Trigger rules

1. Produce announcements from **state changes**, not from every WebSocket
   snapshot. The existing `control_reason` and `emergency_priority.reason` are
   latest decisions, not one-time events. In particular,
   `request_normal_clearance_for_emergency` means a duration request was sent;
   it does not prove that yellow, all-red, or a new green has occurred.
2. Current scenarios use the runner's `emergency_events`: stable event ID,
   vehicle, intersection, state, support flag, and reason. The runner uses
   verified controlled lanes/approaches; never infer a mapping from compass
   words or camera proximity. The policy observes these events without changing
   the simulation or deciding priority itself.
3. Give each emitted announcement a stable ID such as
   `(run_id, vehicle_id, message_id)` for emergencies. Emit each emergency
   stage once per vehicle per run. Reset starts a new run; reconnecting the
   browser must not replay spoken announcements as new events.
4. A new event emits `emergency.detected`. A transition into `priority_active`
   emits `emergency.priority_activated`, even if first seen already active.
   Those messages do not claim that yellow/all-red has finished. Fixed Timing
   and Adaptive Network events do not receive priority-active state from the
   runner, so they produce detection only.
5. After an active event becomes completed or disappears, emit
   `emergency.priority_completed` once. Detection-only events ending do not
   produce this message. Multiple intersections can announce independently.
6. Include simulation time and run ID in the event. The browser ignores
   historical alerts more than eight simulated seconds old, cancels playback
   on a new run, aggregates matching events for 650 ms, and uses one FIFO
   player. The next item starts only after `ended`, error, or timeout; voices
   never overlap.
7. Adaptive plan changes do not trigger speech. A congestion alert needs
   a scenario-specific threshold; when configured, it requires 10 simulated
   seconds above that threshold and resets below 60% of it. No scenario has a
   congestion threshold configured yet.
8. Preserve FIFO order after aggregation. Never claim that the algorithm saved
   time until a fixed/adaptive comparison has been completed.

## Delivery path

```text
SUMO/TraCI snapshot
  -> backend announcement policy (state transitions, deduplication)
  -> bounded `voice_alerts` history in WebSocket snapshots
  -> browser alert list and optional playback of new, timely alerts
  -> GET /api/voice/audio?event_ids=... -> backend validation, aggregation, and ElevenLabs call
  -> browser playback
```

The backend accepts an **existing emitted event ID** for audio retrieval,
not arbitrary browser-supplied text. It calls ElevenLabs only when audio
is requested, caches the result in memory by voice/model/text, and keeps the API key on
the server in `ELEVENLABS_API_KEY`. Configure voice ID and model separately;
do not put secrets, generated clips, or API responses in Git. The official
`POST /v1/text-to-speech/:voice_id/stream` endpoint accepts text and returns
audio bytes progressively. A normal HTTP TTS request is sufficient for these
complete short phrases; an input-streaming WebSocket is unnecessary here.

The UI has an explicit **Enable voice** action before automatic playback:
browsers commonly block audible playback before user interaction. Keep a mute
control and visible captions. On API failure, timeout, missing key, or blocked
playback, leave the text visible and do not delay the simulation.
The browser starts an audio context on that click and adds half a second of
silent audio before each decoded announcement, so the output device is active
before the first spoken syllable.

The snapshot addition and audio route are documented in `docs/DATA_CONTRACTS.md`.

## Acceptance cases for implementation

- Current event-based snapshots produce detection once per vehicle/intersection,
  plus activation and completion only when the event reaches those stages.
- Adaptive cycle-plan changes, scenario selection, Start, Pause, Resume, Reset,
  Stop, and run finish produce no spoken announcement.
- Congestion voice remains disabled until a scenario threshold and hysteresis
  have been configured and tested.
- A conflicting event may announce priority activation when safe clearance is
  requested, but must not claim the emergency approach is already green.
- Legacy snapshots without an event list preserve `already_green` or
  requested/confirmed-green compatibility behavior.
- London aliases are stable across controller/demand modes, appear in aggregate
  speech, and never replace raw IDs in metadata or traffic-control inputs.
- Two simultaneous vehicles, reset, reconnect, pause/resume, and accelerated
  simulation do not duplicate or replay stale audio.
- Audio failures do not alter TraCI decisions or stop a run; captions remain.
- No ElevenLabs API key appears in a browser bundle, WebSocket payload, or log.

## References

- ElevenLabs streaming TTS API: https://elevenlabs.io/docs/api-reference/text-to-speech/stream
- ElevenLabs latency guidance for complete versus incremental text: https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization
- Browser autoplay behavior: https://developer.mozilla.org/en-US/docs/Web/Media/Guides/Autoplay
