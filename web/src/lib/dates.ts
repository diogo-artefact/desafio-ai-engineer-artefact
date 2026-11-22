import type { SessionSummary } from "../types/api";

export interface GroupedSessions {
  today: SessionSummary[];
  earlier: SessionSummary[];
}

function isSameLocalDay(isoDate: string, now: Date): boolean {
  const parsed = new Date(isoDate);
  if (Number.isNaN(parsed.getTime())) {
    return true;
  }
  return (
    parsed.getFullYear() === now.getFullYear() &&
    parsed.getMonth() === now.getMonth() &&
    parsed.getDate() === now.getDate()
  );
}

export function groupSessionsByRecency(
  sessions: SessionSummary[],
  now: Date = new Date(),
): GroupedSessions {
  const today: SessionSummary[] = [];
  const earlier: SessionSummary[] = [];

  for (const session of sessions) {
    if (isSameLocalDay(session.updated_at || session.created_at, now)) {
      today.push(session);
    } else {
      earlier.push(session);
    }
  }

  return { today, earlier };
}
