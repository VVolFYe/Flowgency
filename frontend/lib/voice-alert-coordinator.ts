export interface CoordinatedAlert {
  event_id: string;
  message_id: string;
}

export function groupAlertsForPlayback<T extends CoordinatedAlert>(alerts: T[]): T[][] {
  const groups = new Map<string, T[]>();
  for (const alert of alerts) {
    const key = alert.message_id.startsWith("emergency.") ? alert.message_id : alert.event_id;
    groups.set(key, [...(groups.get(key) ?? []), alert]);
  }
  return [...groups.values()];
}

export class PlaybackGate {
  private active = false;
  maxActiveObserved = 0;

  begin(): boolean {
    if (this.active) return false;
    this.active = true;
    this.maxActiveObserved = Math.max(this.maxActiveObserved, 1);
    return true;
  }

  end(): void { this.active = false; }
  reset(): void { this.active = false; }
  get isActive(): boolean { return this.active; }
}
