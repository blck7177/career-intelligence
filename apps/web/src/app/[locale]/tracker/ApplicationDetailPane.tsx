"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import { Link } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import {
  getApplication,
  transitionApplication,
  updateApplication,
  createAction,
  updateAction,
  addApplicationEvent, deleteApplication, getPlannerSettings } from "@/api/client";
import type { ApplicationDetail, ApplicationUpdate, StatusTransition, ApplicationEventRead } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toaster";
import { fmtTs } from "@/lib/utils";
import { bandOf, BAND } from "@/lib/matchBand";
import { localDateTimeUtc, parseQuickAdd } from "@/lib/quickParse";
import { STATUS_STYLE, FORWARD_NEXT, CLOSE_STATUSES, LIVE_STATUSES, LANE_STYLE, LANE_CYCLE, restoreTargetOf } from "./status";

interface Props {
  applicationId: string | null;
  /** Nudge the server-rendered list to re-fetch after a mutation here. */
  onListChanged?: () => void;
  /** The application is gone. The list owns the selection, so it clears it —
   *  a pane left pointing at a deleted id would refetch into a 404. */
  onDeleted?: (id: string) => void;
  /** Bumped by the LIST when something outside this pane mutated the same
   *  application. The pane's own data is client-fetched, so `router.refresh()`
   *  — which is all a row action can do to the server-rendered list — leaves it
   *  showing pre-mutation state right next to a toast saying it happened. */
  refreshKey?: number;
}

export function ApplicationDetailPane({ applicationId, onListChanged, onDeleted, refreshKey = 0 }: Props) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [data, setData] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [refetchNonce, setRefetchNonce] = useState(0);

  useEffect(() => {
    if (!applicationId) {
      setData(null);
      setLoading(false);
      setError(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(false);
    (async () => {
      try {
        const token = await getToken();
        const app = await getApplication(applicationId, token);
        if (active) {
          setData(app);
          setLoading(false);
        }
      } catch {
        if (active) {
          setError(true);
          setLoading(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [applicationId, getToken, refetchNonce, refreshKey]);

  const mutated = () => {
    setRefetchNonce((n) => n + 1);
    onListChanged?.();
  };

  if (!applicationId) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <p className="text-sm text-center max-w-xs" style={{ color: "var(--ink-muted)" }}>
          {t("selectApplication")}
        </p>
      </div>
    );
  }

  if (loading && !data) {
    return <div className="flex-1 min-h-0 animate-pulse p-8" aria-hidden />;
  }

  if (error || !data) {
    return (
      <div className="flex-1 min-h-0 flex items-center justify-center p-8">
        <p className="text-sm" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
      </div>
    );
  }

  const app = data;
  const style = STATUS_STYLE[app.status] ?? STATUS_STYLE.planned;
  const jobUrl = app.job?.canonical_url ?? "";
  const isHttp = jobUrl.startsWith("http");

  return (
    <div className="flex flex-col flex-1 min-h-0 overflow-hidden" style={{ opacity: loading ? 0.6 : 1 }}>
      {/* Header */}
      <header className="shrink-0 bg-white px-6 py-3.5" style={{ borderBottom: "1px solid var(--border)" }}>
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              {/* The title links to the job's own page — the JD, the
                  intelligence report and the fit analysis all live there, and
                  from here they were only reachable by going back to the job
                  library and searching for it again. The planned queue has had
                  this link since Wave 8; the master-detail never got it. */}
              <h1 className="text-base font-semibold leading-tight" style={{ color: "var(--ink-primary)" }}>
                <Link href={`/jobs/${app.job_id}`} className="hover:underline">
                  {app.job?.title ?? "(untitled role)"}
                </Link>
              </h1>
              <span className="px-1.5 py-0.5 rounded text-2xs font-semibold shrink-0" style={{ background: style.bg, color: style.fg }}>
                {t(`status.${app.status}`)}
              </span>
            </div>
            <div className="text-xs mt-1 flex items-center gap-2 flex-wrap" style={{ color: "var(--ink-muted)" }}>
              <span>{app.job?.company}</span>
              <span>·</span>
              <span>{app.applied_at ? t("appliedOn", { date: fmtTs(app.applied_at) }) : t("notApplied")}</span>
              {app.channel && (<><span>·</span><span>{app.channel}</span></>)}
              {typeof app.fit_score === "number" && (
                <>
                  <span>·</span>
                  <span
                    className="px-1.5 py-0.5 rounded text-2xs font-semibold"
                    style={{ background: BAND[bandOf(app.fit_score)].bg, color: BAND[bandOf(app.fit_score)].fg }}
                  >
                    {t("fitLabel")} {app.fit_score}
                  </span>
                </>
              )}
              {app.resume_run_id && (
                <>
                  <span>·</span>
                  <Link href={`/runs/${app.resume_run_id}`} className="hover:underline" style={{ color: "var(--primary)" }}>
                    {t("resumeTailored")} ↗
                  </Link>
                </>
              )}
            </div>
            <StatusStepper app={app} t={t} />
          </div>
          {/* Two destinations, named apart: this app's page for the analysis,
              the employer's page to actually apply. A title link alone was
              missable — the report that prompted this said "there is no button
              to get to the detail page", with the title link not yet existing
              either. */}
          <div className="shrink-0 flex items-center gap-3">
            <Link
              href={`/jobs/${app.job_id}`}
              className="inline-flex items-center gap-1 text-xs font-medium hover:underline"
              style={{ color: "var(--primary)" }}
            >
              {t("jobDetails")} →
            </Link>
            {isHttp && (
              <a
                href={jobUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-medium hover:underline"
                style={{ color: "var(--ink-muted)" }}
              >
                <ExternalLink size={13} />
                {t("viewJob")}
              </a>
            )}
          </div>
        </div>
      </header>

      {/* key={app.id} remounts the stateful sections on selection change so a
          typed-but-unsaved note / action draft / transition error never carries
          over to (and silently overwrites) a different application. Mirrors the
          jobs pane's key={job.id} on JobDetailTabs. */}
      <div key={app.id} className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-6">
        {/* Attributes: lane / excitement / contact (editable) */}
        <MetaSection app={app} onMutated={mutated} getToken={getToken} t={t} />

        {/* Status transitions */}
        <StatusSection app={app} onMutated={mutated} onDeleted={onDeleted} getToken={getToken} t={t} />

        {/* Next actions */}
        <ActionsSection app={app} onMutated={mutated} getToken={getToken} t={t} />

        {/* Interviews (rounds are events, not statuses) */}
        <InterviewSection app={app} onMutated={mutated} getToken={getToken} t={t} />

        {/* Timeline (with manual "log a note" entry) */}
        <TimelineSection app={app} onMutated={mutated} getToken={getToken} t={t} />

        {/* Notes */}
        <NotesSection app={app} onMutated={mutated} getToken={getToken} t={t} />
      </div>
    </div>
  );
}

type Getter = () => Promise<string | null>;
type T = ReturnType<typeof useTranslations>;

const STEPPER = ["planned", "applied", "in_review", "interviewing", "onsite", "offer"];

function hasOnsiteEvent(app: ApplicationDetail): boolean {
  return (app.events ?? []).some(
    (e) => e.event_type === "interview_scheduled" &&
      (e.payload_json as { round_type?: string } | null)?.round_type === "onsite",
  );
}

// Which linear step the application sits on. Onsite is derived (an onsite
// interview event on an interviewing app); closed states fall off the chain.
function currentStep(app: ApplicationDetail): number {
  switch (app.status) {
    case "offer": return 5;
    case "interviewing": return hasOnsiteEvent(app) ? 4 : 3;
    case "in_review": return 2;
    case "applied": return 1;
    case "planned": return 0;
    default: return -1; // rejected | withdrawn | ghosted
  }
}

/** Visual status progression (mockup dhead stepper): Planned → … → Offer.
 *  Closed applications grey the chain and show a closed badge. */
/** Shared with ApplicationPeek — the same chain has to read identically in the
 *  side panel and the full pane, or the two disagree about where an
 *  application stands. */
export function StatusStepper({ app, t }: { app: ApplicationDetail; t: T }) {
  const cur = currentStep(app);
  const closed = cur === -1;
  return (
    <div className="mt-2 flex items-center gap-1 flex-wrap text-2xs">
      {STEPPER.map((k, i) => {
        const done = !closed && i < cur;
        const isCur = !closed && i === cur;
        const color = done ? "var(--match-good-fg)" : isCur ? "var(--primary)" : "var(--ink-faint)";
        return (
          <span key={k} className="flex items-center gap-1">
            {i > 0 && <span style={{ color: "var(--ink-faint)" }}>›</span>}
            <span className="inline-flex items-center gap-1" style={{ color, fontWeight: isCur ? 600 : 400 }}>
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: done || isCur ? color : "var(--border-strong, var(--border))" }}
              />
              {t(`funnelStage.${k}`)}
            </span>
          </span>
        );
      })}
      {closed && (
        <span className="ml-1.5 px-1.5 py-0.5 rounded" style={{ background: "var(--match-partial-bg)", color: "var(--match-partial-fg)" }}>
          {t(`status.${app.status}`)}
        </span>
      )}
    </div>
  );
}

function MetaSection({ app, onMutated, getToken, t }: { app: ApplicationDetail; onMutated: () => void; getToken: Getter; t: T }) {
  const [lane, setLane] = useState<string | null>(app.lane ?? null);
  const [excitement, setExcitement] = useState<number>(app.excitement ?? 0);
  const [contactName, setContactName] = useState(app.contact_name ?? "");
  const [contactNote, setContactNote] = useState(app.contact_note ?? "");
  const [savingContact, setSavingContact] = useState(false);
  const contactDirty =
    contactName !== (app.contact_name ?? "") || contactNote !== (app.contact_note ?? "");

  async function patch(fields: ApplicationUpdate) {
    try {
      const token = await getToken();
      await updateApplication(app.id, fields, token);
      onMutated();
    } catch {
      // keep the optimistic value; reselecting the row refetches and reconciles
    }
  }

  function cycleLane() {
    const next = LANE_CYCLE[(LANE_CYCLE.indexOf(lane) + 1) % LANE_CYCLE.length];
    setLane(next);
    patch({ lane: next });
  }

  function setStar(n: number) {
    const next = excitement === n ? 0 : n; // clicking the current value clears it
    setExcitement(next);
    patch({ excitement: next === 0 ? null : next });
  }

  async function saveContact() {
    setSavingContact(true);
    try {
      await patch({ contact_name: contactName || null, contact_note: contactNote || null });
    } finally {
      setSavingContact(false);
    }
  }

  const laneStyle = lane ? LANE_STYLE[lane] : null;
  const labelCls = "text-2xs font-semibold uppercase tracking-wide mb-1";
  const inputCls = "h-8 px-2.5 rounded-md border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20";
  const inputStyle = { borderColor: "var(--border)", color: "var(--foreground)" } as const;

  return (
    <section className="flex flex-wrap items-start gap-x-6 gap-y-3">
      <div>
        <div className={labelCls} style={{ color: "var(--ink-faint)" }}>{t("laneLabel")}</div>
        <button
          onClick={cycleLane}
          className="px-2.5 py-1 rounded-full text-xs font-bold border"
          style={laneStyle ? { background: laneStyle.bg, color: laneStyle.fg, borderColor: "transparent" } : { color: "var(--ink-muted)", borderColor: "var(--border)" }}
        >
          {lane ? lane.toUpperCase() : "—"}
        </button>
      </div>
      <div>
        <div className={labelCls} style={{ color: "var(--ink-faint)" }}>{t("excitementLabel")}</div>
        <div className="flex items-center gap-0.5">
          {[1, 2, 3].map((n) => (
            <button
              key={n}
              onClick={() => setStar(n)}
              aria-label={`${t("excitementLabel")} ${n}`}
              className="text-base leading-none"
              style={{ color: n <= excitement ? "var(--primary)" : "var(--ink-faint)" }}
            >
              ★
            </button>
          ))}
        </div>
      </div>
      <div className="flex-1 min-w-[200px]">
        <div className={labelCls} style={{ color: "var(--ink-faint)" }}>{t("contactLabel")}</div>
        <div className="flex flex-col gap-1.5">
          <input value={contactName} onChange={(e) => setContactName(e.target.value)} placeholder={t("contactNamePlaceholder")} className={inputCls} style={inputStyle} />
          <input value={contactNote} onChange={(e) => setContactNote(e.target.value)} placeholder={t("contactNotePlaceholder")} className={inputCls} style={inputStyle} />
          {contactDirty && (
            <div><Button size="sm" variant="outline" onClick={saveContact} loading={savingContact}>{t("saveContact")}</Button></div>
          )}
        </div>
      </div>
    </section>
  );
}

function StatusSection({ app, onMutated, onDeleted, getToken, t }: { app: ApplicationDetail; onMutated: () => void; onDeleted?: (id: string) => void; getToken: Getter; t: T }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const forward = FORWARD_NEXT[app.status] ?? [];
  const closable = LIVE_STATUSES.includes(app.status);
  const closed = CLOSE_STATUSES.includes(app.status);
  const reopenTarget = restoreTargetOf(app);

  async function move(status: string, opts?: { force?: boolean; note?: string }) {
    setBusy(status);
    setErr(null);
    try {
      const token = await getToken();
      await transitionApplication(
        app.id,
        { status: status as StatusTransition["status"], force: opts?.force ?? false, note: opts?.note },
        token,
      );
      onMutated();
    } catch (e) {
      setErr(t("transitionFailed", { msg: e instanceof Error ? e.message : "error" }));
    } finally {
      setBusy(null);
    }
  }

  // A closed application used to render nothing here: FORWARD_NEXT has no exit
  // from a closed status and LIVE_STATUSES excludes it, so the whole section
  // returned null and a mis-marked row could only be corrected with curl or
  // SQL. Every close on this page is one click and unconfirmed, and the
  // ghosted one is raised by a heuristic that says out loud it cannot see the
  // user's inbox — so the recoverable half is the half that has to exist.
  // (mockup_final_0726.html:1088/:1090 promised exactly this: "之后若对方回来，
  // 可 force 恢复".)
  // Removal is for mistakes, and a mistake is always still `planned` — a wrong
  // URL, a duplicate, a row typed to try the box. Past that the record is
  // history the funnel and the weekly snapshots are counted from, so it closes
  // out instead of disappearing. The server enforces the same line (409).
  const removable = app.status === "planned";

  async function remove() {
    setRemoving(true);
    setErr(null);
    try {
      const token = await getToken();
      await deleteApplication(app.id, token);
      setConfirmRemove(false);
      onDeleted?.(app.id);
    } catch (e) {
      setErr(t("transitionFailed", { msg: e instanceof Error ? e.message : "error" }));
      setConfirmRemove(false);
    } finally {
      setRemoving(false);
    }
  }

  if (forward.length === 0 && !closable && !closed && !removable) return null;

  return (
    <section className="space-y-2">
      {forward.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>{t("moveTo")}</span>
          {forward.map((s) => (
            <Button key={s} size="sm" variant="outline" loading={busy === s} disabled={busy !== null} onClick={() => move(s)}>
              {t(`status.${s}`)}
            </Button>
          ))}
        </div>
      )}
      {closable && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium" style={{ color: "var(--ink-muted)" }}>{t("closeAs")}</span>
          {CLOSE_STATUSES.map((s) => (
            <Button key={s} size="sm" variant="ghost" loading={busy === s} disabled={busy !== null} onClick={() => move(s)}>
              {t(`status.${s}`)}
            </Button>
          ))}
        </div>
      )}
      {closed && (
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            size="sm"
            variant="outline"
            loading={busy === reopenTarget}
            disabled={busy !== null}
            onClick={() => move(reopenTarget, { force: true, note: t("reopenNote") })}
          >
            {t("reopenAs", { status: t(`status.${reopenTarget}`) })}
          </Button>
          <span className="text-2xs" style={{ color: "var(--ink-faint)" }}>{t("reopenHint")}</span>
        </div>
      )}
      {removable && (
        <div className="flex items-center gap-2 flex-wrap pt-1">
          <Button size="sm" variant="ghost" disabled={busy !== null} onClick={() => setConfirmRemove(true)}>
            {t("removeApplication")}
          </Button>
          <span className="text-2xs" style={{ color: "var(--ink-faint)" }}>{t("removeHint")}</span>
        </div>
      )}
      <Dialog open={confirmRemove} onOpenChange={(o) => { if (!removing) setConfirmRemove(o); }}>
        <DialogContent className="max-w-sm">
          <DialogTitle className="text-base font-semibold">{t("removeConfirmTitle")}</DialogTitle>
          <DialogDescription className="text-xs mt-1" style={{ color: "var(--ink-muted)" }}>
            {t("removeConfirmBody", { title: app.job?.title ?? "" })}
          </DialogDescription>
          <div className="flex items-center gap-2 mt-4">
            <span className="flex-1" />
            <Button size="sm" variant="ghost" disabled={removing} onClick={() => setConfirmRemove(false)}>
              {t("removeCancel")}
            </Button>
            <Button size="sm" variant="destructive" loading={removing} onClick={remove}>
              {t("removeConfirm")}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      {err && <p className="text-xs text-rose-600">{err}</p>}
    </section>
  );
}

function ActionsSection({ app, onMutated, getToken, t }: { app: ApplicationDetail; onMutated: () => void; getToken: Getter; t: T }) {
  const [title, setTitle] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const open = (app.actions ?? []).filter((a) => a.status === "pending");

  async function add() {
    const title_ = title.trim();
    if (!title_) return;
    setAdding(true);
    try {
      const token = await getToken();
      // Parsed rather than hardcoded "custom": typing "outreach to Jane" here is
      // the only way a networking to-do gets created, and until now this call
      // filed it as custom — so the outreach counter could never be fed from the
      // UI at all.
      //
      // Only the type is honoured. This pane shows no parse preview and offers no
      // way to undo one, and the type keyword stays in the title — so reading it
      // changes nothing the user can see go wrong. Dates would need a workspace
      // timezone (not available here) and durations would silently cut text out
      // of the title with no chip to object to, which is the one thing this
      // feature is built not to do.
      const parsed = parseQuickAdd(title_, null, { accept: { duration: false } });
      await createAction(
        {
          type: parsed.type?.value ?? "custom",
          title: title_,
          application_id: app.id,
        },
        token,
      );
      setTitle("");
      onMutated();
    } finally {
      setAdding(false);
    }
  }

  async function complete(id: string) {
    setBusyId(id);
    try {
      const token = await getToken();
      await updateAction(id, { op: "complete", snooze_days: 1 }, token);
      onMutated();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-muted)" }}>
        {t("actions")}
      </h2>
      {open.length === 0 ? (
        <p className="text-sm mb-2" style={{ color: "var(--ink-faint)" }}>{t("noActions")}</p>
      ) : (
        <ul className="space-y-1.5 mb-2">
          {open.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate" style={{ color: "var(--ink-secondary)" }}>
                {a.auto_generated && (
                  <span
                    className="inline-block w-1.5 h-1.5 rounded-full mr-1.5 align-middle"
                    style={{ background: "var(--primary)" }}
                    title={t("autoGenerated")}
                    aria-label={t("autoGenerated")}
                  />
                )}
                {a.title}
                {a.due_at && <span className="ml-2 text-2xs" style={{ color: "var(--ink-faint)" }}>{fmtTs(a.due_at)}</span>}
              </span>
              <Button size="sm" variant="ghost" loading={busyId === a.id} onClick={() => complete(a.id)}>
                {t("complete")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-2">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
          placeholder={t("actionTitlePlaceholder")}
          className="flex-1 min-w-0 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
          style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
        />
        <Button size="sm" onClick={add} disabled={!title.trim()} loading={adding}>{t("add")}</Button>
      </div>
    </section>
  );
}

function TimelineSection({ app, onMutated, getToken, t }: { app: ApplicationDetail; onMutated: () => void; getToken: Getter; t: T }) {
  const [note, setNote] = useState("");
  const [adding, setAdding] = useState(false);
  const events = [...(app.events ?? [])].reverse();

  async function add() {
    if (adding) return; // in-flight guard (double-Enter / double-tap) — commit5 lesson
    const msg = note.trim();
    if (!msg) return;
    setAdding(true);
    try {
      const token = await getToken();
      await addApplicationEvent(app.id, { message: msg }, token);
      setNote("");
      onMutated();
    } catch {
      // keep the typed note so the user can retry
    } finally {
      setAdding(false);
    }
  }

  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-muted)" }}>
        {t("timeline")}
      </h2>
      <div className="flex items-center gap-2 mb-3">
        <input
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !adding) add(); }}
          placeholder={t("logNotePlaceholder")}
          className="flex-1 min-w-0 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
          style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
        />
        <Button size="sm" variant="outline" onClick={add} disabled={!note.trim()} loading={adding}>{t("logNote")}</Button>
      </div>
      {events.length === 0 ? (
        <p className="text-sm" style={{ color: "var(--ink-faint)" }}>{t("noEvents")}</p>
      ) : (
        <ul className="space-y-2">
          {events.map((e) => (
            <li key={e.id} className="text-sm flex items-baseline gap-2">
              <span className="text-2xs tabular-nums shrink-0" style={{ color: "var(--ink-faint)" }}>{fmtTs(e.created_at)}</span>
              <span style={{ color: "var(--ink-secondary)" }}>{eventLabel(e, t)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** Friendly timeline label. Interview events carry {round_type, at} in payload;
 *  everything else shows its note (or a humanized event_type fallback).
 *  Shared with ApplicationPeek, which shows the most recent few. */
export function eventLabel(e: ApplicationEventRead, t: T): string {
  if (e.event_type === "interview_scheduled") {
    const p = (e.payload_json ?? {}) as { round_type?: string; at?: string };
    const round = p.round_type ? t(`round.${p.round_type}`) : t("interviewGeneric");
    return t("interviewLogged", { round, date: p.at ? fmtTs(p.at) : "" });
  }
  // Every status change since P0 has recorded from/to; the timeline was
  // throwing it away and printing "Status changed" for all of them. Reading it
  // back costs nothing and fixes the existing history too, not just new rows.
  // A note (why) is shown alongside the move (what), never instead of it.
  if (e.event_type === "status_changed") {
    const p = (e.payload_json ?? {}) as { from?: string; to?: string };
    // Only translate statuses we have labels for: next-intl renders a missing
    // key as the key itself, so an unrecognised status would print
    // "tracker.status.whatever" into the timeline (V6's lesson).
    const known = (s?: string) => !!s && (LIVE_STATUSES.includes(s) || CLOSE_STATUSES.includes(s));
    const label = known(p.from) && known(p.to)
      ? t("statusChangedFromTo", { from: t(`status.${p.from}`), to: t(`status.${p.to}`) })
      : t("statusChanged");
    return e.message ? `${label} — ${e.message}` : label;
  }
  if (e.message) return e.message;
  return e.event_type;
}

const INTERVIEW_ROUNDS = ["recruiter_screen", "phone", "onsite", "final"] as const;

function InterviewSection({ app, onMutated, getToken, t }: { app: ApplicationDetail; onMutated: () => void; getToken: Getter; t: T }) {
  const [round, setRound] = useState<string>("recruiter_screen");
  const [when, setWhen] = useState(""); // datetime-local string
  const [busy, setBusy] = useState(false);

  /**
   * The timezone is read at submit time, matching the Reschedule action in the
   * list: caching it at mount would pin the encoding to whatever the config was
   * when the pane opened.
   *
   * `datetime-local` hands back a bare wall time with no zone. Reading it with
   * `new Date(when)` — what this did — interprets it in the BROWSER's zone, so a
   * user travelling, or simply working from a different zone than the
   * workspace, stored an instant that is not the time they typed. Every other
   * timezone slip in the tracker is a display bug that a refresh corrects; this
   * one persists, and it is the instant the week grid places interview blocks
   * by, so it would put them in the wrong slot for as long as the row lives.
   */
  async function add() {
    if (busy || !when) return;
    setBusy(true);
    try {
      const token = await getToken();
      const cfg = await getPlannerSettings(token);
      const at = cfg.timezone ? localDateTimeUtc(when, cfg.timezone) : null;
      if (!at) {
        // Refuse rather than fall back to the browser clock: a wrong instant
        // here is indistinguishable from a right one once it is stored.
        toast.error(t("interviewTimeUnresolved"));
        return;
      }
      await addApplicationEvent(app.id, { event_type: "interview_scheduled", round_type: round, at }, token);
      setWhen("");
      onMutated();
    } catch {
      // keep the input for retry
    } finally {
      setBusy(false);
    }
  }

  const inputCls = "h-8 px-2.5 rounded-md border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20";
  const inputStyle = { borderColor: "var(--border)", color: "var(--foreground)" } as const;

  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-muted)" }}>
        {t("interviews")}
      </h2>
      <div className="flex items-center gap-2 flex-wrap">
        <select value={round} onChange={(e) => setRound(e.target.value)} className={inputCls} style={inputStyle}>
          {INTERVIEW_ROUNDS.map((r) => (
            <option key={r} value={r}>{t(`round.${r}`)}</option>
          ))}
        </select>
        <input type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} className={inputCls} style={inputStyle} />
        <Button size="sm" variant="outline" onClick={add} disabled={!when} loading={busy}>{t("addInterview")}</Button>
      </div>
    </section>
  );
}

function NotesSection({ app, onMutated, getToken, t }: { app: ApplicationDetail; onMutated: () => void; getToken: Getter; t: T }) {
  const [notes, setNotes] = useState(app.notes ?? "");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty = notes !== (app.notes ?? "");

  async function save() {
    setSaving(true);
    setSaved(false);
    try {
      const token = await getToken();
      await updateApplication(app.id, { notes }, token);
      setSaved(true);
      onMutated();
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <h2 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-muted)" }}>
        {t("notes")}
      </h2>
      <textarea
        value={notes}
        onChange={(e) => { setNotes(e.target.value); setSaved(false); }}
        placeholder={t("notesPlaceholder")}
        rows={4}
        className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20 resize-y"
        style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
      />
      <div className="flex items-center gap-2 mt-2">
        <Button size="sm" variant="outline" onClick={save} disabled={!dirty} loading={saving}>{t("saveNotes")}</Button>
        {saved && !dirty && <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{t("saved")}</span>}
      </div>
    </section>
  );
}
