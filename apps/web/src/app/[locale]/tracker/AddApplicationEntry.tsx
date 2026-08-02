"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, Loader2, CheckCircle2 } from "lucide-react";
import { useApiToken } from "@/hooks/useApiToken";
import { importJob, createApplication } from "@/api/client";
import type { JobImportBody } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useSlowHint } from "@/hooks/useSlowHint";

/** "+ Add" entry for the tracker: two feed chutes into the same pipeline — a job
 *  URL (fetch+extract) or a pasted JD (company+title+text) — then create the
 *  application. The job you want to log isn't always in the discovery library.
 *
 *  @param onAdded fires the moment the application exists, so the caller can
 *    select it while the confirmation is still on screen.
 *  @param onDone fires when the confirmation has had its turn and this closes.
 *    A caller that unmounts on `onAdded` never lets the banner be read — which
 *    is the whole reason it exists — so anything that replaces this component
 *    on success waits for `onDone` instead. */
export function AddApplicationEntry({
  onAdded,
  onDone,
}: {
  onAdded: (applicationId: string) => void;
  onDone?: () => void;
}) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"url" | "paste">("url");
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  // What just landed, held for a beat so "done" is a thing you SEE rather than
  // a panel that vanishes. The whole operation used to end in silence: the form
  // closed, the new row appeared at the top of a list the eye was not on, and a
  // fetch that had just run for twenty seconds reported nothing at all.
  const [added, setAdded] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Only the URL path can be slow — the paste path synthesises a manual:// URL
  // and never leaves the process.
  const slow = useSlowHint(busy && mode === "url");

  const canSubmit =
    mode === "url"
      ? url.trim().length > 0
      : company.trim().length > 0 && title.trim().length > 0 && jd.trim().length > 0;

  // The success banner closes itself. Cleared on unmount so a navigation
  // mid-countdown does not setState into a dead tree.
  useEffect(() => {
    if (added === null) return;
    const id = setTimeout(() => { setAdded(null); close(); onDone?.(); }, 2600);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [added]);

  function close() {
    setOpen(false);
    setAdded(null);
    setUrl("");
    setCompany("");
    setTitle("");
    setJd("");
    setError(null);
  }

  async function submit() {
    if (busy || !canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const token = await getToken();
      const body: JobImportBody =
        mode === "url"
          ? { url: url.trim() }
          : { company: company.trim(), title: title.trim(), jd_text: jd };
      const { job } = await importJob(body, token);
      const label = `${job.title ?? ""} @ ${job.company ?? ""}`;
      try {
        const app = await createApplication({ job_id: job.id, status: "planned" }, token);
        // Select it first, then say so: the banner and the newly opened row
        // appear together rather than the panel closing onto an unchanged list.
        onAdded(app.id);
        setAdded(t("addedBanner", { label }));
      } catch (e) {
        // 409 → an application already exists for this job; treat as "already
        // tracked" and jump to the existing one rather than erroring.
        if ((e as { status?: number }).status === 409) {
          const existingId = parseExistingApplicationId(e);
          if (existingId) {
            onAdded(existingId);
            setAdded(t("addedExistsBanner", { label }));
          }
        } else {
          throw e;
        }
      }
    } catch (e) {
      const msg = (e as Error)?.message?.slice(0, 140) || "error";
      setError(t("addError", { msg }));
    } finally {
      setBusy(false);
    }
  }

  const inputCls =
    "w-full h-9 px-3 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20";
  const inputStyle = { borderColor: "var(--border)", color: "var(--foreground)" } as const;

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-xs font-medium"
        style={{ border: "1px solid var(--border)", color: "var(--ink-secondary)" }}
      >
        <Plus size={13} />
        {t("addEntry")}
      </button>
    );
  }

  return (
    <div
      className="rounded-lg p-3 space-y-2.5"
      style={{ border: "1px solid var(--border)", background: "var(--secondary)" }}
    >
      <div className="flex items-center gap-1.5" hidden={busy || added !== null}>
        {(["url", "paste"] as const).map((m) => (
          <button
            key={m}
            disabled={busy}
            onClick={() => { setMode(m); setError(null); }}
            className="h-7 px-2.5 rounded-md text-xs font-medium"
            style={
              mode === m
                ? { background: "var(--ink-primary)", color: "#fff" }
                : { border: "1px solid var(--border)", color: "var(--ink-secondary)" }
            }
          >
            {t(m === "url" ? "addByUrl" : "addByPaste")}
          </button>
        ))}
      </div>

      {busy ? (
        <div
          className="flex items-start gap-2.5 rounded-lg border px-3 py-2.5"
          role="status"
          aria-live="polite"
          style={{ borderColor: "var(--primary)", background: "var(--muted)" }}
        >
          <Loader2 size={16} className="animate-spin mt-0.5 shrink-0" style={{ color: "var(--primary)" }} />
          <div className="min-w-0">
            <div className="text-sm font-semibold" style={{ color: "var(--ink-primary)" }}>
              {t(mode === "url" ? "addBusyBanner" : "addBusyBannerPaste")}
            </div>
            {slow && (
              <div className="text-2xs mt-0.5" style={{ color: "var(--ink-muted)" }}>{t("addSlowHint")}</div>
            )}
          </div>
        </div>
      ) : added ? (
        <div
          className="flex items-start gap-2.5 rounded-lg border px-3 py-2.5"
          role="status"
          aria-live="polite"
          style={{ borderColor: "var(--match-good-fg)", background: "var(--match-good-bg)" }}
        >
          <CheckCircle2 size={16} className="mt-0.5 shrink-0" style={{ color: "var(--match-good-fg)" }} />
          <div className="text-sm font-semibold min-w-0" style={{ color: "var(--match-good-fg)" }}>{added}</div>
        </div>
      ) : mode === "url" ? (
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && canSubmit && !busy) submit(); }}
          placeholder={t("addUrlPlaceholder")}
          className={inputCls}
          style={inputStyle}
          disabled={busy}
          autoFocus
        />
      ) : (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder={t("addCompanyPlaceholder")} className={inputCls} style={inputStyle} disabled={busy} autoFocus />
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("addTitlePlaceholder")} className={inputCls} style={inputStyle} disabled={busy} />
          </div>
          <textarea
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            placeholder={t("addJdPlaceholder")}
            rows={5}
            className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20 resize-y"
            style={inputStyle}
            disabled={busy}
          />
        </div>
      )}

      {error && <p className="text-xs text-rose-600">{error}</p>}

      {/* While the fetch runs, or while the result is being announced, the form
          is replaced by the banner above — there is nothing to press and
          nothing to edit, and leaving disabled controls on screen reads as a
          frozen page rather than a working one. */}
      {!busy && !added && (
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={submit} disabled={!canSubmit}>{t("addSubmit")}</Button>
          <Button size="sm" variant="ghost" onClick={close}>{t("addCancel")}</Button>
        </div>
      )}
    </div>
  );
}

function parseExistingApplicationId(e: unknown): string | null {
  try {
    const parsed = JSON.parse((e as Error).message);
    return parsed?.detail?.existing_application_id ?? parsed?.existing_application_id ?? null;
  } catch {
    return null;
  }
}
