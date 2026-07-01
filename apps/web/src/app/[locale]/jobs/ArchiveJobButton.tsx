"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "@/i18n/navigation";
import { useApiToken } from "@/hooks/useApiToken";
import { archiveJob } from "@/api/client";

export function ArchiveJobButton({ jobId }: { jobId: string }) {
  const t = useTranslations("common");
  const getToken = useApiToken();
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleArchive() {
    setLoading(true);
    try {
      const token = await getToken();
      await archiveJob(jobId, token);
      router.refresh();
    } catch {
      setLoading(false);
      setConfirming(false);
    }
  }

  if (confirming) {
    return (
      <span className="flex items-center gap-1.5">
        <button
          onClick={handleArchive}
          disabled={loading}
          className="text-[13px] font-medium text-rose-600 hover:text-rose-800 disabled:opacity-50"
        >
          {loading ? t("removing") : t("confirm")}
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-[13px] text-zinc-400 hover:text-zinc-600"
        >
          {t("cancel")}
        </button>
      </span>
    );
  }

  return (
    <button
      onClick={() => setConfirming(true)}
      className="text-[13px] text-zinc-400 hover:text-rose-500 transition-colors"
    >
      {t("remove")}
    </button>
  );
}
