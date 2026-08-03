"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { getApplication, addApplicationEvent, transitionApplication, updateAction } from "@/api/client";
import { toast } from "@/components/ui/toaster";
import { addDays, localDateOf, localMidnightUtc } from "@/lib/quickParse";
import type { ActionRead, ApplicationDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { PeekSurface } from "./PeekSurface";
import { fmtTs } from "@/lib/utils";
import { bandOf, BAND } from "@/lib/matchBand";
import { STATUS_STYLE, LANE_STYLE } from "./status";
import { StatusStepper, eventLabel, MetaSection, StatusSection, InterviewSection } from "./ApplicationDetailPane";
import { estOf } from "./capacity";

// Enough to answer "where does this stand" without turning the panel into the
// full timeline — that is what the full page is for, one click away.
const RECENT_EVENTS = 3;

type T = ReturnType<typeof useTranslations>;

interface Props {
  /** The to-do this was opened from. null = closed, or opened from the sidebar
   *  instead. Its `application_id` decides whether there is context to load at
   *  all: a global to-do ("refill the queue") belongs to no application. */
  action: ActionRead | null;
  /** Opened from the sidebar rather than from a to-do — the application IS the
   *  subject, and there is no action to act on. Exactly one of these two is set. */
  applicationId?: string | null;
  onClose: () => void;
  /** Each resolves true when the mutation landed, so the panel only claims
   *  something happened when it did. */
  onComplete: (a: ActionRead) => Promise<boolean>;
  onSnooze: (a: ActionRead) => Promise<boolean>;
  onDismiss: (a: ActionRead) => Promise<boolean>;
  /** The rule's reason line, rendered by the same function as the Today row so
   *  the two can never explain the same to-do differently. */
  reason: (a: ActionRead) => string | null;
  /** A note logged here writes an ApplicationEvent, which is what the funnel's
   *  check-in alert measures staleness from — so the panel has to tell the day
   *  view that its pipeline snapshot is now out of date. */
  onApplicationChanged: () => void;
  /** The verbs move work, not just records: Drop makes the server retire this
   *  application's pending to-dos and takes it out of the queue, Reschedule
   *  changes the day one of them is owed on. Both leave stale rows on screen —
   *  in Today's list and in the sidebar — unless the lists themselves are
   *  re-read, which no amount of context refreshing does (usePlannerData keeps
   *  the action list out of PlannerSource on purpose). The queue table this
   *  panel replaced knew that: its Drop reloaded the planner and its own list
   *  together. */
  onActionsChanged: () => void;
  /** Workspace zone and the server's today, for Reschedule. Passed in rather
   *  than fetched: plannerSources.test.ts allows getPlannerWeek in exactly two
   *  files, and a panel quietly opening a third copy of the week is the shape
   *  that守卫 exists to stop. Missing either disables the button. */
  tz?: string | null;
  serverToday?: string | null;
}

/**
 * The application behind a to-do, without leaving Today.
 *
 * Ticking a row is a decision, and a decision needs context: what this company
 * is, how far along it is, what was said last. Before this, getting that meant
 * leaving the day's list for a separate tab and finding your way back.
 *
 * The rule here was "read-only apart from the to-do buttons and a note", so
 * that a panel opened to answer a question could not also be where a stray
 * click changed your data. That still holds, but it is now stated as what it
 * actually protects: NO UNCONFIRMED MUTATION. The queue table that used to own
 * Apply / Tailor / Drop is gone, and those verbs had to live
 * somewhere — Apply opens the employer's page in a new tab and Tailor
 * navigates, neither of which changes anything, and Drop is the one real
 * mutation and asks first. Editing lane, excitement and status still stays in
 * the full pane.
 */
export function ApplicationPeek({
  action, applicationId, onClose, onComplete, onSnooze, onDismiss, reason,
  onApplicationChanged, onActionsChanged, tz, serverToday,
}: Props) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  // Whichever entry it was opened from. A to-do's application wins when both
  // are somehow set, since the to-do is the more specific subject.
  const appId = action?.application_id ?? applicationId ?? null;
  const open = action !== null || !!applicationId;
  const [app, setApp] = useState<ApplicationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [busy, setBusy] = useState<"complete" | "snooze" | "dismiss" | null>(null);

  useEffect(() => {
    if (!appId) {
      setApp(null);
      setFailed(false);
      return;
    }
    let active = true;
    setLoading(true);
    setFailed(false);
    (async () => {
      try {
        const token = await getToken();
        const detail = await getApplication(appId, token);
        if (active) setApp(detail);
      } catch {
        // The to-do buttons still work without it — the panel degrades to the
        // action alone rather than becoming a dead end.
        if (active) setFailed(true);
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [appId, getToken, nonce]);

  async function run(kind: "complete" | "snooze" | "dismiss") {
    if (!action || busy) return;
    setBusy(kind);
    try {
      const fn = kind === "complete" ? onComplete : kind === "snooze" ? onSnooze : onDismiss;
      const ok = await fn(action);
      // Closing on failure would hide the fact that nothing happened; the row
      // is back on the list behind the panel either way.
      if (ok) onClose();
    } finally {
      setBusy(null);
    }
  }

  const style = app ? (STATUS_STYLE[app.status] ?? STATUS_STYLE.planned) : null;

  /* Overview or the editing form. Editing is a mode of this panel rather than a
     different page, because "change the status" is the commonest reason anyone
     left it — but the full page keeps every deep link, and the timeline and the
     long notes still live there. */
  const [view, setView] = useState<"peek" | "edit">("peek");
  const [nudged, setNudged] = useState(false);

  /* Back to the overview whenever the subject changes or the panel closes: a
     form opened for one application must not still be standing when the next
     one arrives. */
  useEffect(() => {
    setView("peek");
    setNudged(false);
  }, [appId, open]);

  useEffect(() => {
    if (!nudged) return;
    const id = window.setTimeout(() => setNudged(false), 2400);
    return () => window.clearTimeout(id);
  }, [nudged]);

  /* Escape steps back out of the form before it closes the panel, and a click
     outside does neither — it says so instead. The asymmetry is the point:
     pressing Escape is a decision to leave, so losing a half-typed note is what
     was asked for; catching the page with a stray click is not, and silently
     throwing the form away for it would be the panel's fault. */
  /* Every edit here moves rows, not just readings. A transition can close the
     application, which retires its pending to-dos server-side; the sidebar has
     to move the row between its groups; lane and excitement are drawn on the
     queue rows; an interview is drawn on the week strip. `onActionsChanged` is
     the wide channel — its handler re-reads the planner (which re-reads the
     week with it) and the sidebar's own list — so it is the right one for all
     of them, and `nonce` re-reads the record this panel is showing. */
  function afterEdit() {
    setNonce((n) => n + 1);
    onActionsChanged();
  }

  function interceptDismiss(reason: "escape" | "outside"): boolean {
    if (view !== "edit") return false;
    if (reason === "escape") {
      setView("peek");
      return true;
    }
    setNudged(true);
    return true;
  }

  return (
    <PeekSurface
      open={open}
      // The row to sit level with: the to-do when one opened it, otherwise the
      // sidebar row for the application itself — the same precedence the panel
      // already uses to decide what it is about.
      anchorId={action?.id ?? appId ?? null}
      onClose={onClose}
      onDismiss={interceptDismiss}
      label={app?.job?.company || action?.title || t("peekLoading")}
    >
        {(action || app || loading) && (
          <>
            <header className="shrink-0 px-5 pt-5 pb-3 pr-10" style={{ borderBottom: "1px solid var(--border)" }}>
              <h2 className="text-base font-semibold" style={{ color: "var(--ink-primary)" }}>
                {app?.job?.company || action?.title || t("peekLoading")}
              </h2>
              <div className="text-xs mt-1 flex items-center gap-2 flex-wrap" style={{ color: "var(--ink-muted)" }}>
                {app ? (
                  <>
                    {/* Same destination as the full pane's title. A peek is
                        where you decide whether a to-do is worth doing, and
                        "what is this role again" is the question it exists to
                        answer. */}
                    <Link href={`/jobs/${app.job_id}`} className="truncate hover:underline">
                      {app.job?.title ?? t("untitledRole")}
                    </Link>
                    {style && (
                      <span
                        className="px-1.5 py-0.5 rounded text-2xs font-semibold shrink-0"
                        style={{ background: style.bg, color: style.fg }}
                      >
                        {t(`status.${app.status}`)}
                      </span>
                    )}
                    {/* At the top because it is a primary act, not an escape
                        hatch. It leads to the full page, which owns every edit
                        the panel deliberately does not offer (the status
                        machine, the interview form, lane and excitement) — and
                        the name says the main reason people go there, rather
                        than describing the navigation. */}
                    {view === "peek" ? (
                      <button
                        type="button"
                        onClick={() => setView("edit")}
                        className="ml-auto shrink-0 text-xs font-medium hover:underline"
                        style={{ color: "var(--primary)" }}
                      >
                        {t("peekEditStatus")}
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setView("peek")}
                        className="ml-auto shrink-0 text-xs font-medium hover:underline"
                        style={{ color: "var(--primary)" }}
                      >
                        {t("peekBackToOverview")}
                      </button>
                    )}
                  </>
                ) : (
                  <span>{appId ? (failed ? t("loadFailed") : "…") : t("peekManualAction")}</span>
                )}
              </div>
            </header>

            <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-5">
              {action && (
                <CurrentAction action={action} reason={reason} busy={busy} onRun={run} t={t} />
              )}

              {app && view === "edit" && (
                <>
                  {/* The same components the full page renders, with the same
                      four props — the record, a token getter, a translator, and
                      what to do afterwards. Nothing here knows it is in a panel,
                      which is why the two cannot drift apart. */}
                  <MetaSection app={app} onMutated={afterEdit} getToken={getToken} t={t} />
                  <StatusSection
                    app={app}
                    onMutated={afterEdit}
                    // A removed application has no panel to return to.
                    onDeleted={() => { onActionsChanged(); onClose(); }}
                    getToken={getToken}
                    t={t}
                  />
                  <InterviewSection app={app} onMutated={afterEdit} getToken={getToken} t={t} />

                  {nudged && (
                    <p className="text-2xs" role="status" style={{ color: "var(--warn-fg)" }}>
                      {t("peekEditingHint")}
                    </p>
                  )}

                  {/* The rest of the record — the whole timeline, the long notes
                      — is still the full page's, and this is the way there. */}
                  <Link
                    href={`/tracker/${app.id}`}
                    className="block text-2xs hover:underline"
                    style={{ color: "var(--ink-faint)" }}
                  >
                    {t("peekOpenFull")}
                  </Link>
                </>
              )}

              {app && view === "peek" && (
                <>
                  <ApplicationVerbs
                    app={app}
                    tz={tz ?? null}
                    serverToday={serverToday ?? null}
                    // Only the wider of the two: the reload behind
                    // onActionsChanged re-reads the funnel on its way past, so
                    // firing both would put two reads of the same endpoint in
                    // the air for one click.
                    onChanged={() => { setNonce((n) => n + 1); onActionsChanged(); }}
                    // A drop ends the conversation: its to-dos are retired
                    // server-side, so leaving the panel open would leave
                    // Complete / Tomorrow / Not needed drawn over a row that no
                    // longer exists — and "Tomorrow" on a retired to-do is a
                    // request the server now refuses.
                    onDropped={() => { onActionsChanged(); onClose(); }}
                    t={t}
                  />

                  <Section title={t("statusLabel")}>
                    <StatusStepper app={app} t={t} />
                  </Section>

                  <Section title={t("peekOverview")}>
                    <Overview app={app} t={t} />
                  </Section>

                  <Section title={t("timeline")}>
                    <RecentTimeline app={app} t={t} />
                  </Section>

                  {/* key={app.id}: a note typed for one application must never
                      survive into another. Same reason the full pane keys its
                      stateful sections — that one shipped as a high-severity
                      finding in P0 (switching rows overwrote someone's notes). */}
                  <NoteBox
                    key={app.id}
                    app={app}
                    onLogged={() => {
                      setNonce((n) => n + 1);
                      onApplicationChanged();
                    }}
                    t={t}
                  />
                </>
              )}

              {appId && failed && !app && (
                <p className="text-sm" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
              )}
              {appId && loading && !app && !failed && <div className="animate-pulse h-24" aria-hidden />}
            </div>

          </>
        )}
    </PeekSurface>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-2xs font-semibold uppercase tracking-wide mb-1.5" style={{ color: "var(--ink-faint)" }}>
        {title}
      </h3>
      {children}
    </section>
  );
}

/** The to-do itself, carrying the reason the engine raised it. "Not needed"
 *  dismisses: the suppression set remembers it, which is what makes the button
 *  different from snoozing forever. */
function CurrentAction({ action, reason, busy, onRun, t }: {
  action: ActionRead;
  reason: (a: ActionRead) => string | null;
  busy: "complete" | "snooze" | "dismiss" | null;
  onRun: (kind: "complete" | "snooze" | "dismiss") => void;
  t: T;
}) {
  const why = reason(action);
  return (
    <Section title={t("peekCurrentAction")}>
      <div className="rounded-lg border px-3 py-2.5" style={{ borderColor: "var(--border)" }}>
        <div className="text-sm font-medium" style={{ color: "var(--ink-primary)" }}>{action.title}</div>
        <div className="text-2xs mt-0.5" style={{ color: "var(--ink-faint)" }}>
          {why && <>{why} · </>}
          {t("estMinutes", { minutes: estOf(action) })}
          {action.auto_generated && <> · {t("autoGenerated")}</>}
        </div>
        <div className="flex items-center gap-2 mt-2.5">
          <Button size="sm" onClick={() => onRun("complete")} loading={busy === "complete"} disabled={!!busy}>
            {t("complete")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => onRun("snooze")} loading={busy === "snooze"} disabled={!!busy}>
            {t("ritualCarryTomorrow")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onRun("dismiss")} loading={busy === "dismiss"} disabled={!!busy}>
            {t("peekDismiss")}
          </Button>
        </div>
      </div>
    </Section>
  );
}

/** Only facts the record actually carries — an empty field is left out rather
 *  than printed as a dash, which reads as "measured and zero". */
function Overview({ app, t }: { app: ApplicationDetail; t: T }) {
  const lane = app.lane ? LANE_STYLE[app.lane] : null;
  const items: Array<[string, React.ReactNode]> = [];
  if (typeof app.fit_score === "number") {
    items.push([
      t("fitLabel"),
      <span
        key="fit"
        className="px-1.5 py-0.5 rounded text-2xs font-semibold"
        style={{ background: BAND[bandOf(app.fit_score)].bg, color: BAND[bandOf(app.fit_score)].fg }}
      >
        {app.fit_score}
      </span>,
    ]);
  }
  if (app.lane) {
    items.push([
      t("laneLabel"),
      <span
        key="lane"
        className="px-1.5 py-0.5 rounded-full text-2xs font-bold"
        style={lane ? { background: lane.bg, color: lane.fg } : undefined}
      >
        {app.lane.toUpperCase()}
      </span>,
    ]);
  }
  if (app.excitement) {
    items.push([t("excitementLabel"), <span key="exc">{"★".repeat(app.excitement)}</span>]);
  }
  if (app.channel) items.push([t("peekChannel"), app.channel]);
  items.push([
    t("colAge"),
    app.applied_at ? t("appliedOn", { date: fmtTs(app.applied_at) }) : t("notApplied"),
  ]);
  if (app.contact_name) items.push([t("contactLabel"), app.contact_name]);

  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
      {items.map(([label, value], i) => (
        <div key={i} className="flex items-center gap-1.5">
          <dt style={{ color: "var(--ink-faint)" }}>{label}</dt>
          <dd className="font-medium" style={{ color: "var(--ink-secondary)" }}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function RecentTimeline({ app, t }: { app: ApplicationDetail; t: T }) {
  const events = [...(app.events ?? [])].reverse();
  if (events.length === 0) {
    return <p className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("noEvents")}</p>;
  }
  return (
    <>
      <ul className="space-y-1.5">
        {events.slice(0, RECENT_EVENTS).map((e) => (
          <li key={e.id} className="text-xs flex items-baseline gap-2">
            <span className="text-2xs tabular-nums shrink-0" style={{ color: "var(--ink-faint)" }}>
              {fmtTs(e.created_at)}
            </span>
            <span style={{ color: "var(--ink-secondary)" }}>{eventLabel(e, t)}</span>
          </li>
        ))}
      </ul>
      {events.length > RECENT_EVENTS && (
        <Link
          href={`/tracker/${app.id}`}
          className="inline-block mt-1.5 text-2xs hover:underline"
          style={{ color: "var(--primary)" }}
        >
          {t("peekAllEvents", { n: events.length })}
        </Link>
      )}
    </>
  );
}

function NoteBox({ app, onLogged, t }: { app: ApplicationDetail; onLogged: () => void; t: T }) {
  const getToken = useApiToken();
  const [note, setNote] = useState("");
  const [adding, setAdding] = useState(false);

  async function add() {
    if (adding) return; // in-flight guard, same as the full pane
    const msg = note.trim();
    if (!msg) return;
    setAdding(true);
    try {
      const token = await getToken();
      await addApplicationEvent(app.id, { message: msg }, token);
      setNote("");
      onLogged();
    } catch {
      // keep the text so it can be retried
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !adding) add(); }}
        placeholder={t("logNotePlaceholder")}
        className="flex-1 min-w-0 h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20"
        style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
      />
      <Button size="sm" variant="outline" onClick={add} disabled={!note.trim()} loading={adding}>
        {t("logNote")}
      </Button>
    </div>
  );
}

/**
 * What you can do to an application from here.
 *
 * These are the queue table's verbs, which arrived here when the table went.
 * The panel's rule is no UNCONFIRMED mutation, and each of them clears it a
 * different way: Apply opens the employer's page in a new tab and changes
 * nothing here, Tailor navigates, Reschedule moves one to-do by one day and is
 * reversible from the row it moved, and Drop — the one irreversible thing —
 * asks first.
 *
 * Apply only appears for a real http posting: a pasted JD has a synthesised
 * `manual://` URL that would open to nothing.
 */
function ApplicationVerbs({
  app, tz, serverToday, onChanged, onDropped, t,
}: {
  app: ApplicationDetail;
  tz: string | null;
  serverToday: string | null;
  /** A to-do moved, but this application is still open and still the subject. */
  onChanged: () => void;
  /** This application is closed. Separate from onChanged because the panel has
   *  to stop being a panel about actionable work: the server has just retired
   *  every pending to-do here, and the buttons above them are still drawn from
   *  the copy this panel loaded before that happened. */
  onDropped: () => void;
  t: T;
}) {
  const getToken = useApiToken();
  const [busy, setBusy] = useState<"drop" | "defer" | null>(null);
  const [confirmDrop, setConfirmDrop] = useState(false);
  const url = app.job?.canonical_url ?? "";
  const isHttp = url.startsWith("http");
  const planned = app.status === "planned";

  // The soonest pending to-do with a date — what "put this off a day" acts on.
  const next = (app.actions ?? [])
    .filter((a) => a.status === "pending" && a.due_at)
    .sort((x, y) => new Date(x.due_at!).getTime() - new Date(y.due_at!).getTime() || x.id.localeCompare(y.id))[0];

  async function drop() {
    if (busy) return;
    setBusy("drop");
    try {
      const token = await getToken();
      await transitionApplication(app.id, { status: "withdrawn", force: false, note: t("dropNote") }, token);
      toast(t("dropNote"));
      onDropped();
    } catch {
      toast.error(t("rowActionFailed"));
    } finally {
      setBusy(null);
      setConfirmDrop(false);
    }
  }

  async function defer() {
    // Anchored on the LATER of today and the to-do's own due date, so this only
    // ever pushes out — the first version of this in the list quietly pulled a
    // to-do due next week FORWARD. Never computed from the browser clock.
    if (busy || !next?.due_at || !tz || !serverToday) return;
    setBusy("defer");
    try {
      const token = await getToken();
      const dueDate = localDateOf(next.due_at, tz);
      const anchor = dueDate > serverToday ? dueDate : serverToday;
      await updateAction(
        next.id,
        { op: "snooze", snooze_days: 1, snooze_until: localMidnightUtc(addDays(anchor, 1), tz) },
        token,
      );
      toast(t("rowRescheduled"));
      onChanged();
    } catch {
      toast.error(t("rowActionFailed"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* An anchor, not a button that calls window.open: this is a link to
          somebody else's site, and middle-click, cmd-click and "copy link
          address" are how people open a job posting. The queue table's version
          was an anchor; keeping the verb meant keeping that too. */}
      {planned && isHttp && (
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className={buttonVariants({ size: "sm" })}
        >
          {t("applyNow")}
        </a>
      )}
      {/* The job's own page — where the JD, the fit report and resume
          tailoring live. Distinct from the footer's link, which opens this
          APPLICATION's full page; they were briefly both labelled the same. */}
      <Link href={`/jobs/${app.job_id}`} className="inline-flex">
        <Button size="sm" variant="outline">{t("peekJobPage")}</Button>
      </Link>
      {next && tz && serverToday && (
        <Button size="sm" variant="outline" onClick={defer} loading={busy === "defer"} disabled={!!busy}>
          {t("rowReschedule")}
        </Button>
      )}
      {planned && (
        confirmDrop ? (
          <span className="inline-flex items-center gap-1.5">
            <span className="text-2xs" style={{ color: "var(--ink-muted)" }}>{t("dropConfirmAsk")}</span>
            <Button size="sm" variant="outline" onClick={drop} loading={busy === "drop"} disabled={!!busy}>
              {t("dropConfirmYes")}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmDrop(false)} disabled={!!busy}>
              {t("cancelShort")}
            </Button>
          </span>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirmDrop(true)} disabled={!!busy}>
            {t("drop")}
          </Button>
        )
      )}
    </div>
  );
}
