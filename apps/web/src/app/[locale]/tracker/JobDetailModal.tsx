"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getProfile, listFitReports } from "@/api/client";
import type { ProfileRead } from "@/api/client";
import { useApiToken } from "@/hooks/useApiToken";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { JobDetailPane } from "../jobs/JobDetailPane";

/**
 * The job behind an application, read without leaving the plan.
 *
 * Following a link to /jobs/[id] answered the question and cost the page: the
 * panel, the row it was anchored to, the day being planned. "What is this role
 * again" is a question asked WHILE tracking, so it is answered here and the
 * tracker is still underneath when it closes.
 *
 * A real modal, unlike the peek it opens from. The peek is a glance you keep
 * working around; a job description is a thing you read, and two stacked
 * non-modal surfaces would put two sets of Escape and outside-click rules on
 * the same screen. The deep link stays, in the pane's own header, for the tools
 * that belong to the job library rather than to a day's planning.
 *
 * The contents are the jobs list's own pane — a client component that fetches
 * job, latest report and fit report from an id. Everything it needs beyond the
 * id is fetched HERE rather than threaded down: the tracker page is a server
 * component four client components above this one, and none of them has any
 * reason to know what a profile is.
 */
export function JobDetailModal({
  jobId,
  onClose,
}: {
  /** null = closed. */
  jobId: string | null;
  onClose: () => void;
}) {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [profile, setProfile] = useState<ProfileRead | null>(null);
  /** undefined = still looking, null = analysed nothing for this job yet. */
  const [fitId, setFitId] = useState<string | null | undefined>(undefined);

  useEffect(() => {
    if (!jobId) {
      setFitId(undefined);
      return;
    }
    let active = true;
    (async () => {
      const token = await getToken();
      const p = profile ?? (await getProfile(token).catch(() => null));
      if (!active) return;
      setProfile(p);
      // The pane fetches a fit report only when handed its id, and an
      // application carries a fit SCORE without one. Without this lookup the
      // Fit tab would read "no fit analysis" for a job the tracker is already
      // showing a score for — the two surfaces contradicting each other about
      // the same job.
      if (!p) {
        setFitId(null);
        return;
      }
      const list = await listFitReports({ profile_id: p.id }, token).catch(() => null);
      if (!active) return;
      setFitId(list?.items.find((fr) => fr.job_id === jobId)?.id ?? null);
    })();
    return () => {
      active = false;
    };
    // `profile` is read but deliberately not a dependency: it is fetched once
    // and reused, and listing it would re-run this the moment it arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, getToken]);

  return (
    <Dialog open={jobId !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent
        // The default popup is a padded max-w-md block with no height, and the
        // pane inside expects a flex column with one — it is built to fill a
        // master-detail pane and scroll internally, not to make its own page.
        // The pane draws its own header cluster in the top-right (Open full
        // page / Favorite / Not interested), which is exactly where the
        // dialog's close button is absolutely positioned — they overlap. The
        // pane keeps its corner; the close button is nudged out to the frame.
        className="max-w-[min(960px,calc(100vw-48px))] h-[min(82vh,760px)] p-0 pt-9 flex flex-col overflow-hidden"
      >
        {/* The pane draws its own heading; this is the accessible name, which
            Base UI requires and which the visible header does not provide. */}
        <DialogTitle className="sr-only">{t("jobModalTitle")}</DialogTitle>
        {/* Keyed on the job so nothing survives from the last one opened — the
            pane keeps fetched state and a mutation nonce of its own. */}
        {jobId && fitId !== undefined && (
          <JobDetailPane key={jobId} jobId={jobId} profile={profile} fitReportId={fitId} libraryActions={false} />
        )}
        {jobId && fitId === undefined && (
          <div className="flex-1 animate-pulse m-4 rounded-lg" style={{ background: "var(--muted)" }} aria-hidden />
        )}
      </DialogContent>
    </Dialog>
  );
}
