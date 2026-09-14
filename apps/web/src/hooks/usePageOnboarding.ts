import { useEffect, useRef, useState } from "react";
import type { GuidedTourStep } from "../components/GuidedTour";
import type { AdminUser } from "../types/dashboard";

const dismissedInSession = new Set<string>();

function dismissed(key: string): boolean {
  if (dismissedInSession.has(key)) return true;
  try { return window.localStorage.getItem(key) === "dismissed"; }
  catch { return false; }
}

/** Read-only tour state: deliberately accepts no business actions or form setters. */
export function usePageOnboarding({ currentUser, page, steps, busy = false }: {
  currentUser: AdminUser;
  page: string;
  steps: readonly GuidedTourStep[];
  busy?: boolean;
}) {
  const key = `dy-data:page-onboarding:v1:${page}:${currentUser.user_id ?? currentUser.username}`;
  const [preference, setPreference] = useState(() => ({ key, dismissed: dismissed(key) }));
  const [session, setSession] = useState<{ key: string; index: number } | null>(null);
  const replayRef = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    setPreference({ key, dismissed: dismissed(key) });
    setSession(null);
  }, [key]);
  useEffect(() => { if (busy) setSession(null); }, [busy]);
  const dismissInvitation = () => {
    dismissedInSession.add(key);
    try { window.localStorage.setItem(key, "dismissed"); } catch { /* session fallback */ }
    setPreference({ key, dismissed: true });
  };
  const finish = () => { dismissInvitation(); setSession(null); };
  const index = session?.key === key ? session.index : 0;
  return {
    replayRef,
    disabled: busy || steps.length === 0,
    start: () => { if (!busy && steps.length) setSession({ key, index: 0 }); },
    dismissInvitation,
    showInvitation: !busy && !session && preference.key === key && !preference.dismissed,
    running: !busy && session?.key === key && Boolean(steps[index]),
    tourProps: {
      step: steps[index], index, total: steps.length,
      nextLabel: index === steps.length - 1 ? "完成引导" : "下一步",
      onNext: () => index === steps.length - 1 ? finish() : setSession({ key, index: index + 1 }),
      onPrevious: index > 0 ? () => setSession({ key, index: index - 1 }) : undefined,
      onClose: finish,
      returnFocusRef: replayRef,
    },
  };
}
