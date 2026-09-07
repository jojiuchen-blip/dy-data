import { useCallback, useEffect, useRef, useState } from "react";
import type { GuidedTourStep } from "../components/GuidedTour";
import type { AdminUser, ClueAssignmentRound } from "../types/dashboard";

const preferencePrefix = "dy-data:clue-onboarding:v1:";
const dismissedThisSession = new Set<string>();

function wasDismissed(key: string): boolean {
  if (dismissedThisSession.has(key)) return true;
  try {
    return window.localStorage.getItem(key) === "dismissed";
  } catch {
    return false;
  }
}

function rememberDismissal(key: string) {
  dismissedThisSession.add(key);
  try {
    window.localStorage.setItem(key, "dismissed");
  } catch {
    // The current account can still dismiss and replay when storage is blocked.
  }
}

interface Options {
  currentUser: AdminUser;
  isDetailsView: boolean;
  candidateRound?: ClueAssignmentRound;
  candidateCanOperate: boolean;
  roundsReady: boolean;
  roundsLoading: boolean;
  roundsRefreshing: boolean;
  roundsError?: string;
  detailReady: boolean;
  detailLoading: boolean;
  detailError: string | null;
  detailHasSelectedRound: boolean;
  canEditFollowUp: boolean;
  canShowPhone: boolean;
  selectedRoundId: string | null;
  busy: boolean;
  mobileFiltersOpen: boolean;
  setMobileFiltersOpen: (open: boolean) => void;
  openDetail: (row: ClueAssignmentRound, trigger?: HTMLElement | null) => void;
  closeDetail: () => void;
}

interface TourSession {
  owner: string;
  step: number;
  round: ClueAssignmentRound | null;
  filtersWereOpen: boolean;
}

const tourSteps: GuidedTourStep[] = [
  {
    id: "navigation",
    title: "先找到要跟进的线索",
    description: "从「线索明细」进入工作列表。接下来，一起看一遍从找线索到记录跟进的流程。",
    target: '[data-clue-tour="navigation"]',
  },
  {
    id: "status",
    title: "从「待跟进」开始",
    description: "在「线索状态」中选择「待跟进」，就能找到尚未记录跟进的线索。也可以结合门店、日期和商品筛选；本次引导会保留你当前的筛选。",
    target: ".clue-tour-status",
  },
  {
    id: "detail",
    title: "打开一条线索",
    description: "点击「查看详情」，可查看客户联系方式、订单和跟进记录。点击下一步，带你打开当前列表中的一条线索。",
    target: '[data-clue-tour="open-detail"]',
  },
  {
    id: "contact",
    title: "查看联系方式，联系客户",
    description: "有操作权限时，可按需查看或复制完整手机号。联系客户后再记录本次结果；引导不会替你查看或复制号码。",
    target: '[data-clue-tour="contact"]',
  },
  {
    id: "follow-up",
    title: "记下这次跟进的结果",
    description: "选择符合实际的跟进结果，再在下方备注中写下沟通结论、客户需求或约定时间，方便下次接着跟进。",
    target: '[data-clue-tour="follow-up"]',
  },
  {
    id: "save",
    title: "确认后，保存本次跟进",
    description: "填写并确认结果、备注后，点击这里保存。战败或要求换门店会结束当前轮次，请按真实情况选择。本次引导只作说明，不会提交记录。",
    target: '[data-clue-tour="save"]',
  },
  {
    id: "history",
    title: "下次跟进前，先看历史",
    description: "每一轮分配和跟进记录都在这里。先了解之前的沟通，再继续服务客户。以后可从页面上的「新手引导」重新查看。",
    target: '[data-clue-tour="history"]',
  },
];

/** Coordinates existing UI actions only; it has no business API or form setters. */
export function useClueOnboarding(options: Options) {
  const key = preferencePrefix + (options.currentUser.user_id ?? options.currentUser.username);
  const allowed = options.currentUser.page_keys.includes("A02");
  const [preference, setPreference] = useState(() => ({ key, dismissed: wasDismissed(key) }));
  const [session, setSessionState] = useState<TourSession | null>(null);
  const sessionRef = useRef<TourSession | null>(null);
  const optionsRef = useRef(options);
  const replayRef = useRef<HTMLButtonElement | null>(null);
  optionsRef.current = options;

  const setSession = useCallback((next: TourSession | null) => {
    sessionRef.current = next;
    setSessionState(next);
  }, []);

  const finish = useCallback(() => {
    const current = sessionRef.current;
    if (!current) return;
    const latest = optionsRef.current;
    rememberDismissal(current.owner);
    const latestKey = preferencePrefix + (latest.currentUser.user_id ?? latest.currentUser.username);
    setPreference({ key: latestKey, dismissed: wasDismissed(latestKey) });
    // Only close the detail opened by this tour; pre-existing drafts cannot enter it.
    if (current.round?.assignment_round_id === latest.selectedRoundId) {
      latest.closeDetail();
    }
    latest.setMobileFiltersOpen(current.filtersWereOpen);
    setSession(null);
  }, [setSession]);

  useEffect(() => {
    setPreference({ key, dismissed: wasDismissed(key) });
    if (sessionRef.current && (sessionRef.current.owner !== key || !allowed)) finish();
  }, [allowed, finish, key]);

  useEffect(() => {
    if (
      session && session.step > 0 && !options.isDetailsView &&
      window.location.pathname !== "/clues/details"
    ) finish();
  }, [finish, options.isDetailsView, session]);

  const start = () => {
    if (!allowed || options.selectedRoundId || options.busy || sessionRef.current) return;
    setSession({ owner: key, step: 0, round: null, filtersWereOpen: options.mobileFiltersOpen });
  };
  const dismissInvitation = () => {
    rememberDismissal(key);
    setPreference({ key, dismissed: true });
  };

  const stepNumber = session?.step ?? 0;
  const candidate = options.candidateRound;
  const noRows = options.isDetailsView && options.roundsReady &&
    !options.roundsLoading && !options.roundsRefreshing && !candidate;
  const readOnly = options.detailReady ? !options.canEditFollowUp : !options.candidateCanOperate;
  const sequence = noRows ? [0, 1, 2] : readOnly && candidate ? [0, 1, 2, 3, 6] : [0, 1, 2, 3, 4, 5, 6];
  const index = Math.max(0, sequence.indexOf(stepNumber));
  const inDetail = stepNumber >= 3;
  const listFailure = stepNumber === 2 && Boolean(options.roundsError);
  const detailFailure = inDetail && (
    Boolean(options.detailError) ||
    (options.detailReady && !options.detailHasSelectedRound) ||
    (session?.round !== null && options.selectedRoundId !== session?.round?.assignment_round_id)
  );
  const pending = stepNumber === 2
    ? !listFailure && (!options.isDetailsView || !options.roundsReady || options.roundsLoading || options.roundsRefreshing)
    : inDetail && !detailFailure && (options.detailLoading || !options.detailReady);
  const terminal = listFailure || detailFailure || (stepNumber === 2 && noRows) || stepNumber === 6;
  let step = tourSteps[stepNumber];
  let notice: string | undefined;
  if (stepNumber === 2 && noRows && !listFailure) {
    step = {
      ...step, title: "当前筛选下还没有线索", target: '[data-clue-tour="results"]',
      description: "线索会显示在这里。有线索后，点击「查看详情」开始跟进。你可以稍后调整筛选，再从「新手引导」查看完整流程。",
    };
  }
  if (stepNumber === 2 && pending) {
    step = { ...step, target: null };
    notice = "正在加载当前筛选结果，请稍候。";
  }
  if (listFailure || detailFailure) {
    step = { ...step, target: null };
    notice = listFailure
      ? "线索列表暂时加载失败。请结束引导，待页面恢复后重新查看。"
      : "这条线索的详情暂不可用，或当前轮次已发生变化。请结束引导，刷新列表后重新查看。";
  } else if (stepNumber === 3 && options.detailReady && !options.canShowPhone) {
    step = {
      ...step, title: "查看线索状态与联系方式",
      description: "当前线索只展示脱敏联系方式，完整手机号操作以当前轮次的权限为准。你仍可以查看订单与跟进历史。",
    };
  }
  if (inDetail && options.detailReady && readOnly && !detailFailure) {
    notice = "当前线索不可编辑，已跳过填写与保存跟进的说明。";
  }

  const next = () => {
    const current = sessionRef.current;
    if (!current || pending) return;
    if (terminal) { finish(); return; }
    if (stepNumber === 0) {
      if (!options.isDetailsView) {
        window.history.pushState(null, "", `/clues/details${window.location.search}`);
        window.dispatchEvent(new PopStateEvent("popstate"));
      }
      options.setMobileFiltersOpen(true);
      setSession({ ...current, step: 1 });
    } else if (stepNumber === 1) {
      options.setMobileFiltersOpen(current.filtersWereOpen);
      setSession({ ...current, step: 2 });
    } else if (stepNumber === 2 && candidate) {
      options.openDetail(candidate, replayRef.current);
      setSession({ ...current, round: candidate, step: 3 });
    } else {
      setSession({ ...current, step: sequence.find((value) => value > stepNumber) ?? 6 });
    }
  };
  const previous = () => {
    const current = sessionRef.current;
    if (!current || stepNumber === 0) return;
    if (stepNumber === 3) {
      if (current.round?.assignment_round_id === options.selectedRoundId) options.closeDetail();
      setSession({ ...current, round: null, step: 2 });
    } else if (stepNumber === 2) {
      options.setMobileFiltersOpen(true);
      setSession({ ...current, step: 1 });
    } else {
      if (stepNumber === 1) options.setMobileFiltersOpen(current.filtersWereOpen);
      setSession({ ...current, step: [...sequence].reverse().find((value) => value < stepNumber) ?? 0 });
    }
  };

  return {
    allowed,
    replayRef,
    start,
    dismissInvitation,
    running: Boolean(session && session.owner === key && allowed),
    showInvitation: allowed && !session && preference.key === key && !preference.dismissed && !options.selectedRoundId,
    disabled: Boolean(options.selectedRoundId || options.busy),
    targetRoundId: candidate?.assignment_round_id,
    tourProps: {
      step, index, total: sequence.length, pending, notice,
      nextLabel: terminal ? (stepNumber === 6 ? "完成引导" : "结束引导") : "下一步",
      onNext: next,
      onPrevious: stepNumber > 0 ? previous : undefined,
      onClose: finish,
      returnFocusRef: replayRef,
    },
  };
}
