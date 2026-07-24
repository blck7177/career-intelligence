"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import { useApiToken } from "@/hooks/useApiToken";
import {
  getApplication,
  transitionApplication,
  updateApplication,
  createAction,
  updateAction,
} from "@/api/client";
import type { ApplicationDetail, StatusTransition } from "@/api/client";
import { Button } from "@/components/ui/button";
import { fmtTs } from "@/lib/utils";
import { STATUS_STYLE, FORWARD_NEXT, CLOSE_STATUSES, LIVE_STATUSES } from "./status";

interface Props {
  applicationId: string | null;
  /** Nudge the server-rendered list to re-fetch after a mutation here. */
  onListChanged?: () => void;
}

export function ApplicationDetailPane({ applicationId, onListChanged }: Props) {
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
  }, [applicationId, getToken, refetchNonce]);

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
              <h1 className="text-base font-semibold leading-tight" style={{ color: "var(--ink-primary)" }}>
                {app.job?.title ?? "(untitled role)"}
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
            </div>
          </div>
          {isHttp && (
            <a
              href={jobUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="shrink-0 inline-flex items-center gap-1 text-xs font-medium hover:underline"
              style={{ color: "var(--primary)" }}
            >
              <ExternalLink size={13} />
              {t("viewJob")}
            </a>
          )}
        </div>
      </header>

      {/* key={app.id} remounts the stateful sections on selection change so a
          typed-but-unsaved note / action draft / transition error never carries
          over to (and silently overwrites) a different application. Mirrors the
          jobs pane's key={job.id} on JobDetailTabs. */}
      <div key={app.id} className="flex-1 min-h-0 overflow-y-auto px-6 py-5 space-y-6">
        {/* Status transitions */}
        <StatusSection app={app} onMutated={mutated} getToken={getToken} t={t} />

        {/* Next actions */}
        <ActionsSection app={app} onMutated={mutated} getToken={getToken} t={t} />

        {/* Timeline */}
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--ink-muted)" }}>
            {t("timeline")}
          </h2>
          {(app.events ?? []).length === 0 ? (
            <p className="text-sm" style={{ color: "var(--ink-faint)" }}>{t("noEvents")}</p>
          ) : (
            <ul className="space-y-2">
              {[...(app.events ?? [])].reverse().map((e) => (
                <li key={e.id} className="text-sm flex items-baseline gap-2">
                  <span className="text-2xs tabular-nums shrink-0" style={{ color: "var(--ink-faint)" }}>{fmtTs(e.created_at)}</span>
                  <span style={{ color: "var(--ink-secondary)" }}>{e.message || e.event_type}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Notes */}
        <NotesSection app={app} onMutated={mutated} getToken={getToken} t={t} />
      </div>
    </div>
  );
}

type Getter = () => Promise<string | null>;
type T = ReturnType<typeof useTranslations>;

function StatusSection({ app, onMutated, getToken, t }: { app: ApplicationDetail; onMutated: () => void; getToken: Getter; t: T }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const forward = FORWARD_NEXT[app.status] ?? [];
  const closable = LIVE_STATUSES.includes(app.status);

  async function move(status: string) {
    setBusy(status);
    setErr(null);
    try {
      const token = await getToken();
      await transitionApplication(app.id, { status: status as StatusTransition["status"], force: false }, token);
      onMutated();
    } catch (e) {
      setErr(t("transitionFailed", { msg: e instanceof Error ? e.message : "error" }));
    } finally {
      setBusy(null);
    }
  }

  if (forward.length === 0 && !closable) return null;

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
      await createAction({ type: "custom", title: title_, application_id: app.id }, token);
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
