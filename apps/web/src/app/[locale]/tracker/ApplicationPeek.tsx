"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Link } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { getApplication, addApplicationEvent } from "@/api/client";
import type { ActionRead, ApplicationDetail } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { fmtTs } from "@/lib/utils";
import { bandOf, BAND } from "@/lib/matchBand";
import { STATUS_STYLE, LANE_STYLE } from "./status";
import { StatusStepper, eventLabel } from "./ApplicationDetailPane";
import { estOf } from "./capacity";

// Enough to answer "where does this stand" without turning the panel into the
// full timeline — that is what the full page is for, one click away.
const RECENT_EVENTS = 3;

type T = ReturnType<typeof useTranslations>;

interface Props {
  /** The to-do this was opened from. null = closed. Its `application_id`
   *  decides whether there is context to load at all: a global to-do
   *  ("refill the queue") belongs to no application. */
  action: ActionRead | null;
  onClose: () => void;
  /** Each resolves true when the mutation landed, so the panel only claims
   *  something happened when it did. */
  onComplete: (a: ActionRead) => Promise<boolean>;
  onSnooze: (a: ActionRead) => Promise<boolean>;
  onDismiss: (a: ActionRead) => Promise<boolean>;
  /** The rule's reason line, rendered by the same function as the Today row so
   *  the two can never explain the same to-do differently. */
  reason: (a: ActionRead) => string | null;
}

/**
 * The application behind a to-do, without leaving Today.
 *
 * Ticking a row is a decision, and a decision needs context: what this company
 * is, how far along it is, what was said last. Before this, getting that meant
 * leaving the day's list for the Applications view and finding your way back.
 *
 * Read-only by design apart from the to-do buttons and a note. Editing lane,
 * excitement or status stays in the full pane: a panel you opened to answer a
 * question should not also be a place where a stray click changes your data.
 */
export function ApplicationPeek({ action, onClose, onComplete, onSnooze, onDismiss, reason }: Props) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const appId = action?.application_id ?? null;
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

  return (
    <Sheet open={action !== null} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent className="max-w-[430px] flex flex-col gap-0 p-0">
        {action && (
          <>
            <header className="shrink-0 px-5 pt-5 pb-3 pr-10" style={{ borderBottom: "1px solid var(--border)" }}>
              <SheetTitle>{app?.job?.company || action.title}</SheetTitle>
              <div className="text-xs mt-1 flex items-center gap-2 flex-wrap" style={{ color: "var(--ink-muted)" }}>
                {app ? (
                  <>
                    <span className="truncate">{app.job?.title ?? t("untitledRole")}</span>
                    {style && (
                      <span
                        className="px-1.5 py-0.5 rounded text-2xs font-semibold shrink-0"
                        style={{ background: style.bg, color: style.fg }}
                      >
                        {t(`status.${app.status}`)}
                      </span>
                    )}
                  </>
                ) : (
                  <span>{appId ? (failed ? t("loadFailed") : "…") : t("peekManualAction")}</span>
                )}
              </div>
            </header>

            <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-5">
              <CurrentAction action={action} reason={reason} busy={busy} onRun={run} t={t} />

              {app && (
                <>
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
                  <NoteBox key={app.id} app={app} onLogged={() => setNonce((n) => n + 1)} t={t} />
                </>
              )}

              {appId && failed && !app && (
                <p className="text-sm" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
              )}
              {appId && loading && !app && !failed && <div className="animate-pulse h-24" aria-hidden />}
            </div>

            {app && (
              <footer className="shrink-0 px-5 py-3" style={{ borderTop: "1px solid var(--border)" }}>
                <Link
                  href={`/tracker/${app.id}`}
                  className="text-xs font-medium hover:underline"
                  style={{ color: "var(--primary)" }}
                >
                  {t("peekOpenFull")}
                </Link>
              </footer>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
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
