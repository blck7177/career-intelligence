"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useApiToken } from "@/hooks/useApiToken";
import { getPlannerSettings, updatePlannerSettings } from "@/api/client";
import type { PlannerSettings } from "@/api/client";
import { Button } from "@/components/ui/button";

const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

// A fully-required view of the settings (the generated PlannerSettings marks
// default-bearing fields optional; the server always returns them all). We
// normalize on load so the form fields are never `undefined`.
interface Draft {
  timezone: string;
  weekly_target: { apply: number; outreach: number; follow_up: number };
  daily_cap_minutes: number;
  rest_days: string[];
  follow_up_days: number;
  ghost_days: number;
  interview_checkin_days: number;
  fresh_window_days: number;
  apply_or_drop_days: number;
  onsite_target: number;
  active_target: number;
  review_day: string;
  search_started_at: string | null;
}

// Common IANA zones for the picker; the workspace's current value is merged in
// on load so a hand-set zone outside this list is never dropped.
const COMMON_TZ = [
  "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
  "America/Sao_Paulo", "UTC", "Europe/London", "Europe/Berlin", "Europe/Paris",
  "Asia/Kolkata", "Asia/Shanghai", "Asia/Tokyo", "Australia/Sydney",
];

// Mirrors packages/contracts/api/applications.PlannerSettings defaults — used by
// "Restore defaults". Kept in sync manually (the server re-validates on save).
const DEFAULTS: Draft = {
  timezone: "America/New_York",
  weekly_target: { apply: 10, outreach: 5, follow_up: 6 },
  daily_cap_minutes: 90,
  rest_days: ["sat", "sun"],
  follow_up_days: 7,
  ghost_days: 14,
  interview_checkin_days: 7,
  fresh_window_days: 3,
  apply_or_drop_days: 14,
  onsite_target: 4,
  active_target: 15,
  review_day: "sun",
  search_started_at: null,
};

// Fill any field the generated (optional) type left undefined from DEFAULTS.
function normalize(s: PlannerSettings): Draft {
  return {
    timezone: s.timezone ?? DEFAULTS.timezone,
    weekly_target: {
      apply: s.weekly_target?.apply ?? DEFAULTS.weekly_target.apply,
      outreach: s.weekly_target?.outreach ?? DEFAULTS.weekly_target.outreach,
      follow_up: s.weekly_target?.follow_up ?? DEFAULTS.weekly_target.follow_up,
    },
    daily_cap_minutes: s.daily_cap_minutes ?? DEFAULTS.daily_cap_minutes,
    rest_days: s.rest_days ?? DEFAULTS.rest_days,
    follow_up_days: s.follow_up_days ?? DEFAULTS.follow_up_days,
    ghost_days: s.ghost_days ?? DEFAULTS.ghost_days,
    interview_checkin_days: s.interview_checkin_days ?? DEFAULTS.interview_checkin_days,
    fresh_window_days: s.fresh_window_days ?? DEFAULTS.fresh_window_days,
    apply_or_drop_days: s.apply_or_drop_days ?? DEFAULTS.apply_or_drop_days,
    onsite_target: s.onsite_target ?? DEFAULTS.onsite_target,
    active_target: s.active_target ?? DEFAULTS.active_target,
    review_day: s.review_day ?? DEFAULTS.review_day,
    search_started_at: s.search_started_at ?? null,
  };
}

function weekOfSearch(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const start = new Date(iso + "T00:00:00");
  if (isNaN(start.getTime())) return null;
  const days = Math.floor((Date.now() - start.getTime()) / 86400_000);
  return days < 0 ? null : Math.floor(days / 7) + 1;
}

/** Tracker · Settings sub-view. All planner-tunable numbers + timezone +
 *  search-start date. Loads GET /planner-settings, saves via PUT (partial merge,
 *  server re-validates → surfaced 422). */
export function SettingsView() {
  const t = useTranslations("tracker");
  const getToken = useApiToken();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveErr, setSaveErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    try {
      const token = await getToken();
      setDraft(normalize(await getPlannerSettings(token)));
      setLoadErr(false);
    } catch {
      setLoadErr(true);
    }
  }, [getToken]);

  useEffect(() => { load(); }, [load]);

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
    setSaved(false);
  }
  function setTarget(key: keyof Draft["weekly_target"], value: number) {
    setDraft((d) => (d ? { ...d, weekly_target: { ...d.weekly_target, [key]: value } } : d));
    setSaved(false);
  }
  function toggleRestDay(day: string) {
    setDraft((d) => {
      if (!d) return d;
      const has = d.rest_days.includes(day);
      const rest_days = has ? d.rest_days.filter((x) => x !== day) : [...d.rest_days, day];
      return { ...d, rest_days };
    });
    setSaved(false);
  }

  async function save() {
    if (!draft || saving) return;
    setSaving(true);
    setSaveErr(null);
    try {
      const token = await getToken();
      setDraft(normalize(await updatePlannerSettings(draft, token)));
      setSaved(true);
    } catch (e) {
      setSaveErr(e instanceof Error && e.message ? e.message : t("settingsSaveFailed"));
    } finally {
      setSaving(false);
    }
  }

  if (draft === null) {
    return (
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-[var(--space-row-edge)] py-6">
          {loadErr ? (
            <div className="text-center py-8">
              <p className="text-sm mb-3" style={{ color: "var(--ink-muted)" }}>{t("loadFailed")}</p>
              <Button size="sm" variant="outline" onClick={load}>{t("retry")}</Button>
            </div>
          ) : (
            <div className="animate-pulse h-64" aria-hidden />
          )}
        </div>
      </div>
    );
  }

  const wk = weekOfSearch(draft.search_started_at);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-[var(--space-row-edge)] py-6 space-y-6">
        {/* Timezone */}
        <Group title={t("settingsTimezone")} hint={t("settingsTimezoneHint")}>
          <select
            value={draft.timezone}
            onChange={(e) => set("timezone", e.target.value)}
            className="h-9 px-2 rounded-lg border text-sm bg-transparent"
            style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
          >
            {(COMMON_TZ.includes(draft.timezone) ? COMMON_TZ : [draft.timezone, ...COMMON_TZ]).map((z) => (
              <option key={z} value={z}>{z}</option>
            ))}
          </select>
        </Group>

        {/* Weekly targets */}
        <Group title={t("settingsWeeklyTargets")} hint={t("settingsWeeklyTargetsHint")}>
          <div className="flex flex-wrap gap-3">
            <Num label={t("weekApplied")} value={draft.weekly_target.apply} onChange={(v) => setTarget("apply", v)} />
            <Num label={t("weekOutreach")} value={draft.weekly_target.outreach} onChange={(v) => setTarget("outreach", v)} />
            <Num label={t("weekFollowUps")} value={draft.weekly_target.follow_up} onChange={(v) => setTarget("follow_up", v)} />
          </div>
        </Group>

        {/* Daily cap */}
        <Group title={t("settingsDailyCap")} hint={t("settingsDailyCapHint")}>
          <Num label={t("settingsMinutes")} value={draft.daily_cap_minutes} onChange={(v) => set("daily_cap_minutes", v)} />
        </Group>

        {/* Rest days */}
        <Group title={t("settingsRestDays")} hint={t("settingsRestDaysHint")}>
          <div className="flex flex-wrap gap-1.5">
            {WEEKDAYS.map((d) => {
              const on = draft.rest_days?.includes(d);
              return (
                <button
                  key={d}
                  onClick={() => toggleRestDay(d)}
                  className="h-8 px-3 rounded-lg border text-xs capitalize"
                  style={{
                    borderColor: on ? "var(--primary)" : "var(--border)",
                    background: on ? "var(--primary)" : "transparent",
                    color: on ? "var(--primary-foreground)" : "var(--ink-secondary)",
                  }}
                >
                  {t(`weekdayShort.${d}`)}
                </button>
              );
            })}
          </div>
        </Group>

        {/* Follow-up & ghost cadence */}
        <Group title={t("settingsCadence")} hint={t("settingsCadenceHint")}>
          <div className="flex flex-wrap gap-3">
            <Num label={t("settingsFollowUpDays")} value={draft.follow_up_days} onChange={(v) => set("follow_up_days", v)} />
            <Num label={t("settingsGhostDays")} value={draft.ghost_days} onChange={(v) => set("ghost_days", v)} />
            <Num label={t("settingsCheckinDays")} value={draft.interview_checkin_days} onChange={(v) => set("interview_checkin_days", v)} />
            <Num label={t("settingsApplyOrDropDays")} value={draft.apply_or_drop_days} onChange={(v) => set("apply_or_drop_days", v)} />
          </div>
        </Group>

        {/* Freshness */}
        <Group title={t("settingsFreshness")} hint={t("settingsFreshnessHint")}>
          <Num label={t("settingsDays")} value={draft.fresh_window_days} onChange={(v) => set("fresh_window_days", v)} />
        </Group>

        {/* Pipeline targets */}
        <Group title={t("settingsPipelineTargets")} hint={t("settingsPipelineTargetsHint")}>
          <div className="flex flex-wrap gap-3">
            <Num label={t("settingsOnsiteTarget")} value={draft.onsite_target} onChange={(v) => set("onsite_target", v)} />
            <Num label={t("settingsActiveTarget")} value={draft.active_target} onChange={(v) => set("active_target", v)} />
          </div>
        </Group>

        {/* Weekly review day */}
        <Group title={t("settingsReviewDay")} hint={t("settingsReviewDayHint")}>
          <select
            value={draft.review_day}
            onChange={(e) => set("review_day", e.target.value)}
            className="h-9 px-2 rounded-lg border text-sm bg-transparent capitalize"
            style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
          >
            {WEEKDAYS.map((d) => <option key={d} value={d}>{t(`weekdayLong.${d}`)}</option>)}
          </select>
        </Group>

        {/* Search start */}
        <Group title={t("settingsSearchStart")} hint={t("settingsSearchStartHint")}>
          <div className="flex items-center gap-3">
            <input
              type="date"
              value={draft.search_started_at ?? ""}
              onChange={(e) => set("search_started_at", e.target.value || null)}
              className="h-9 px-2 rounded-lg border text-sm bg-transparent"
              style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
            />
            {wk !== null && (
              <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{t("settingsWeekOfSearch", { n: wk })}</span>
            )}
          </div>
        </Group>

        {/* Actions */}
        <div className="flex items-center gap-2 pt-2 border-t" style={{ borderColor: "var(--border)" }}>
          <Button size="sm" onClick={save} loading={saving}>{t("settingsSave")}</Button>
          <Button size="sm" variant="ghost" onClick={() => { setDraft(DEFAULTS); setSaved(false); }}>{t("settingsRestoreDefaults")}</Button>
          {saved && <span className="text-xs" style={{ color: "var(--match-good-fg)" }}>{t("settingsSaved")}</span>}
          {saveErr && <span className="text-xs" style={{ color: "#b45309" }}>{t("settingsSaveFailed")}</span>}
        </div>
      </div>
    </div>
  );
}

function Group({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-xs font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--ink-primary)" }}>{title}</h3>
      {hint && <p className="text-2xs mb-2" style={{ color: "var(--ink-faint)" }}>{hint}</p>}
      {children}
    </section>
  );
}

function Num({ label, value, onChange }: { label: string; value: number; onChange: (v: number) => void }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-2xs uppercase tracking-wide" style={{ color: "var(--ink-faint)" }}>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        onChange={(e) => onChange(e.target.value === "" ? 0 : parseInt(e.target.value, 10))}
        className="w-20 h-9 px-2 rounded-lg border text-sm bg-transparent tabular-nums"
        style={{ borderColor: "var(--border)", color: "var(--foreground)" }}
      />
    </label>
  );
}
