"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { useApiToken } from "@/hooks/useApiToken";
import { importJob, createApplication } from "@/api/client";
import type { JobImportBody } from "@/api/client";
import { Button } from "@/components/ui/button";

/** "+ Add" entry for the tracker: two feed chutes into the same pipeline — a job
 *  URL (fetch+extract) or a pasted JD (company+title+text) — then create the
 *  application. The job you want to log isn't always in the discovery library. */
export function AddApplicationEntry({ onAdded }: { onAdded: (applicationId: string) => void }) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"url" | "paste">("url");
  const [url, setUrl] = useState("");
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [jd, setJd] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit =
    mode === "url"
      ? url.trim().length > 0
      : company.trim().length > 0 && title.trim().length > 0 && jd.trim().length > 0;

  function close() {
    setOpen(false);
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
      try {
        const app = await createApplication({ job_id: job.id, status: "planned" }, token);
        onAdded(app.id);
      } catch (e) {
        // 409 → an application already exists for this job; treat as "already
        // tracked" and jump to the existing one rather than erroring.
        if ((e as { status?: number }).status === 409) {
          const existingId = parseExistingApplicationId(e);
          if (existingId) onAdded(existingId);
        } else {
          throw e;
        }
      }
      close();
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
      <div className="flex items-center gap-1.5">
        {(["url", "paste"] as const).map((m) => (
          <button
            key={m}
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

      {mode === "url" ? (
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && canSubmit && !busy) submit(); }}
          placeholder={t("addUrlPlaceholder")}
          className={inputCls}
          style={inputStyle}
          autoFocus
        />
      ) : (
        <div className="space-y-2">
          <div className="flex gap-2">
            <input value={company} onChange={(e) => setCompany(e.target.value)} placeholder={t("addCompanyPlaceholder")} className={inputCls} style={inputStyle} autoFocus />
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("addTitlePlaceholder")} className={inputCls} style={inputStyle} />
          </div>
          <textarea
            value={jd}
            onChange={(e) => setJd(e.target.value)}
            placeholder={t("addJdPlaceholder")}
            rows={5}
            className="w-full px-3 py-2 rounded-lg border text-sm outline-none focus:ring-2 focus:ring-[var(--primary)]/20 resize-y"
            style={inputStyle}
          />
        </div>
      )}

      {error && <p className="text-xs text-rose-600">{error}</p>}

      <div className="flex items-center gap-2">
        <Button size="sm" onClick={submit} disabled={!canSubmit} loading={busy}>{t("addSubmit")}</Button>
        <Button size="sm" variant="ghost" onClick={close} disabled={busy}>{t("addCancel")}</Button>
      </div>
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
