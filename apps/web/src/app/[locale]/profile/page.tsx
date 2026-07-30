"use client";

import { useEffect, useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { FileUp } from "lucide-react";
import { useApiToken } from "@/hooks/useApiToken";
import {
  createRun,
  listProfiles,
  createProfile,
  updateProfile,
  deleteProfile,
  uploadResume,
  type ProfileRead,
  type ProfileUpdate,
} from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";
import { Button } from "@/components/ui/button";
import { buttonVariants } from "@/components/ui/button-variants";
import { optionPillVariants } from "@/components/ui/option-pill-variants";
import { Badge } from "@/components/ui/badge";
import { Banner } from "@/components/ui/banner";
import { Card } from "@/components/ui/card";
import { Row } from "@/components/ui/row";
import { Skeleton } from "@/components/ui/skeleton";
import { Input, Textarea, Field } from "@/components/ui/input";
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription, DialogClose } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toaster";
import { PageContainer } from "@/components/ui/page-container";
import { PageHeader } from "@/components/ui/page-header";
import { ZoneHead } from "@/components/ui/zone-head";
import { EmptyState } from "@/components/EmptyState";

type FieldState = {
  label: string;
  summary: string;
  experience_summary: string;
  education_summary: string;
  technical_skills: string;
  subject_areas: string;
  tools: string;
  years_experience: string;
};

const EMPTY_FIELDS: FieldState = {
  label: "",
  summary: "",
  experience_summary: "",
  education_summary: "",
  technical_skills: "",
  subject_areas: "",
  tools: "",
  years_experience: "",
};

function profileToFields(p: ProfileRead): FieldState {
  return {
    label: p.label ?? "",
    summary: p.summary ?? "",
    experience_summary: p.experience_summary ?? "",
    education_summary: p.education_summary ?? "",
    technical_skills: ((p.technical_skills ?? []) as string[]).join(", "),
    subject_areas: ((p.subject_areas ?? []) as string[]).join(", "),
    tools: ((p.tools ?? []) as string[]).join(", "),
    years_experience: p.years_experience != null ? String(p.years_experience) : "",
  };
}

function fieldsToUpdate(f: FieldState, serverProfile: ProfileRead | null): ProfileUpdate {
  const parseList = (s: string) =>
    s
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);

  return {
    label: f.label || null,
    summary: f.summary || null,
    experience_summary: f.experience_summary || null,
    education_summary: f.education_summary || null,
    technical_skills: parseList(f.technical_skills).length ? parseList(f.technical_skills) : null,
    subject_areas: parseList(f.subject_areas).length ? parseList(f.subject_areas) : null,
    tools: parseList(f.tools).length ? parseList(f.tools) : null,
    years_experience: f.years_experience ? parseInt(f.years_experience, 10) || null : null,
    representative_projects: serverProfile?.representative_projects ?? null,
  };
}

type ImportStatus = "idle" | "generating" | "ready" | "error";

type ProfileDraft = {
  summary?: string;
  experience_summary?: string;
  education_summary?: string;
  years_experience?: number | null;
  technical_skills?: string[];
  subject_areas?: string[];
  tools?: string[];
  representative_projects?: unknown[];
};

type ParseNotes = {
  low_confidence_items?: string[];
  missing_information?: string[];
  assumptions?: string[];
};

type CleanResumeSummary = {
  markdown?: string;
};

function draftToFields(d: ProfileDraft, currentLabel: string): FieldState {
  return {
    label: currentLabel,
    summary: d.summary ?? "",
    experience_summary: d.experience_summary ?? "",
    education_summary: d.education_summary ?? "",
    technical_skills: (d.technical_skills ?? []).join(", "),
    subject_areas: (d.subject_areas ?? []).join(", "),
    tools: (d.tools ?? []).join(", "),
    years_experience: d.years_experience != null ? String(d.years_experience) : "",
  };
}

export default function ProfilePage() {
  const t = useTranslations("profile");
  const getToken = useApiToken();
  const [fields, setFields] = useState<FieldState>(EMPTY_FIELDS);
  const [allProfiles, setAllProfiles] = useState<ProfileRead[]>([]);
  const [serverProfile, setServerProfile] = useState<ProfileRead | null>(null);
  const [profileHash, setProfileHash] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Resume import state
  const [resumeText, setResumeText] = useState("");
  const [importStatus, setImportStatus] = useState<ImportStatus>("idle");
  const [importError, setImportError] = useState<string | null>(null);
  const [parseNotes, setParseNotes] = useState<ParseNotes | null>(null);
  const [cleanResume, setCleanResume] = useState<CleanResumeSummary | null>(null);
  const [draftProjects, setDraftProjects] = useState<unknown[] | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [uploadingFile, setUploadingFile] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const loadProfiles = useCallback(async (selectId?: string) => {
    try {
      const token = await getToken();
      const profiles = await listProfiles(token);
      setAllProfiles(profiles);
      const target = selectId
        ? profiles.find((p) => p.id === selectId) ?? profiles[0]
        : profiles[0];
      if (target) {
        setFields(profileToFields(target));
        setServerProfile(target);
        setProfileHash(target.profile_hash);
      }
    } catch (err: unknown) {
      if (
        err &&
        typeof err === "object" &&
        "status" in err &&
        (err as { status: number }).status === 404
      ) {
        // No profiles yet
      } else {
        toast.error(t("failedToLoadProfiles"));
      }
    } finally {
      setLoading(false);
    }
  }, [getToken, t]);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  const switchProfile = (profileId: string) => {
    const target = allProfiles.find((p) => p.id === profileId);
    if (target) {
      setFields(profileToFields(target));
      setServerProfile(target);
      setProfileHash(target.profile_hash);
      setImportStatus("idle");
      setResumeText("");
      setParseNotes(null);
      setCleanResume(null);
      setDraftProjects(null);
    }
  };

  const handleChange =
    (key: keyof FieldState) =>
    (e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) =>
      setFields((prev) => ({ ...prev, [key]: e.target.value }));

  const handleSave = async () => {
    setSaving(true);
    try {
      const token = await getToken();
      const payload = fieldsToUpdate(fields, serverProfile);
      const updated = serverProfile
        ? await updateProfile(serverProfile.id, payload, token)
        : await createProfile(payload, token);
      setFields(profileToFields(updated));
      setServerProfile(updated);
      setProfileHash(updated.profile_hash);
      toast.success(t("profileSaved"));
      await loadProfiles(updated.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("saveFailed");
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleNewProfile = async () => {
    setSaving(true);
    try {
      const token = await getToken();
      const created = await createProfile({ label: `Profile ${allProfiles.length + 1}` }, token);
      await loadProfiles(created.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("failedToCreateProfile");
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteProfile = async () => {
    if (!serverProfile) return;
    if (allProfiles.length <= 1) return;
    setSaving(true);
    try {
      const token = await getToken();
      await deleteProfile(serverProfile.id, token);
      await loadProfiles();
      toast.success(t("deleteSuccessToast"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("deleteFailed");
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";

    setUploadingFile(true);
    setUploadError(null);
    try {
      const token = await getToken();
      const result = await uploadResume(file, token);
      setResumeText(result.resume_text);
      setShowImport(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("uploadFailed");
      try {
        const parsed = JSON.parse(msg);
        setUploadError(parsed.detail ?? msg);
      } catch {
        setUploadError(msg);
      }
    } finally {
      setUploadingFile(false);
    }
  };

  const handleImport = async () => {
    if (!resumeText.trim()) return;
    setImportStatus("generating");
    setImportError(null);
    setParseNotes(null);
    setCleanResume(null);
    setDraftProjects(null);

    try {
      const token = await getToken();
      const run = await createRun(
        {
          run_type: "profile_import",
          input_snapshot: { resume_text: resumeText.trim(), source_type: "paste" },
        },
        token,
      );
      const finished = await pollRunUntilDone(run.id, getToken, { intervalMs: 2000, timeoutMs: 120_000 });

      if (finished.status !== "succeeded") {
        const msg = finished.error_message ?? `Import ${finished.status}`;
        setImportStatus("error");
        setImportError(msg);
        toast.error(msg);
        return;
      }

      const summary = finished.result_summary_json as Record<string, unknown> | null;
      const draft = summary?.profile_draft as ProfileDraft | undefined;
      const notes = summary?.parse_notes as ParseNotes | undefined;
      const resume = summary?.clean_resume as CleanResumeSummary | undefined;

      if (!draft) {
        setImportStatus("error");
        setImportError(t("noProfileDraft"));
        toast.error(t("noProfileDraft"));
        return;
      }

      setFields(draftToFields(draft, fields.label));
      setDraftProjects(draft.representative_projects ?? null);
      if (notes) setParseNotes(notes);
      if (resume) setCleanResume(resume);
      setImportStatus("ready");
      toast.success(t("draftLoaded"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("importFailedPeriod");
      setImportStatus("error");
      setImportError(msg);
      toast.error(msg);
    }
  };

  const handleApplyAndSave = async () => {
    setSaving(true);
    try {
      const token = await getToken();
      const payload = fieldsToUpdate(fields, serverProfile);
      if (draftProjects && draftProjects.length > 0) {
        payload.representative_projects = draftProjects;
      }
      const updated = serverProfile
        ? await updateProfile(serverProfile.id, payload, token)
        : await createProfile(payload, token);
      setFields(profileToFields(updated));
      setServerProfile(updated);
      setProfileHash(updated.profile_hash);
      setDraftProjects(null);
      setCleanResume(null);
      setImportStatus("idle");
      setResumeText("");
      setParseNotes(null);
      toast.success(t("profileSaved"));
      await loadProfiles(updated.id);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("saveFailed");
      toast.error(msg);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex-1 overflow-y-auto">
        <PageContainer variant="narrow">
          <span className="sr-only" role="status" aria-live="polite">
            {t("loadingProfile")}
          </span>
          {/* Page identity */}
          <Skeleton className="h-[17px] w-44" />
          <Skeleton className="h-4 w-full max-w-[520px] mt-[var(--space-stack-xs)]" />

          <div className="mt-6 space-y-8">
            {/* Resume import card */}
            <Card className="p-[var(--space-surface-default)] space-y-4">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-3 w-64" />
              <Skeleton className="h-14 w-full" />
            </Card>

            {/* Edit form card */}
            <Card className="p-[var(--space-surface-default)] space-y-5">
              <Skeleton className="h-4 w-28" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-10 w-32" />
            </Card>
          </div>
        </PageContainer>
      </div>
    );
  }

  const subjectAreaList = fields.subject_areas
    .split(",")
    .map((d) => d.trim())
    .filter(Boolean);
  const skillList = fields.technical_skills
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const hasProfileData =
    profileHash && (subjectAreaList.length > 0 || skillList.length > 0 || fields.years_experience);
  // The empty state stands in for the import + edit cards only until the user
  // takes one of the two paths it offers; upload / "paste manually" / an upload
  // error all hand over to the real cards, which own the rest of the flow.
  const showEmptyState = allProfiles.length === 0 && !showImport && !resumeText && !uploadError;

  return (
    <div className="flex-1 overflow-y-auto">
      <PageContainer variant="narrow">
      <PageHeader
        title={t("title")}
        subtitle={t("subtitle")}
        gutter="none"
        actions={
          <button
            className={buttonVariants({ variant: "outline", size: "sm" })}
            onClick={handleNewProfile}
            disabled={saving}
          >
            {t("newProfile")}
          </button>
        }
      />

      {/* Profile tabs */}
      {allProfiles.length > 1 && (
        <div className="flex gap-1 mt-4 flex-wrap">
          {allProfiles.map((p) => {
            const active = serverProfile?.id === p.id;
            const displayLabel = p.label || t("profileTabFallback", { n: allProfiles.indexOf(p) + 1 });
            return (
              <button
                key={p.id}
                onClick={() => switchProfile(p.id)}
                className={optionPillVariants({ selected: active })}
              >
                {displayLabel}
              </button>
            );
          })}
        </div>
      )}

      <div className="mt-6 space-y-8">
        {/* Profile Summary Card */}
        {hasProfileData && (
          <Card className="p-[var(--space-surface-default)] space-y-4">
            <ZoneHead
              title={t("profileOverview")}
              sub={
                profileHash ? (
                  <Badge variant="secondary" className="font-mono text-2xs px-1.5">
                    {profileHash.slice(0, 8)}
                  </Badge>
                ) : undefined
              }
            />

            {fields.years_experience && (
              <div className="flex items-center gap-2 text-sm">
                <span className="text-xs" style={{ color: "var(--ink-muted)" }}>{t("experience")}</span>
                <span className="font-semibold" style={{ color: "var(--ink-primary)" }}>{t("years", { count: fields.years_experience })}</span>
              </div>
            )}

            {subjectAreaList.length > 0 && (
              <div>
                <p className="text-xs mb-2" style={{ color: "var(--ink-muted)" }}>{t("subjectAreas")}</p>
                <div className="flex flex-wrap gap-1.5">
                  {subjectAreaList.map((d) => (
                    <Badge key={d} variant="match-good">
                      {d}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {skillList.length > 0 && (
              <div>
                <p className="text-xs mb-2" style={{ color: "var(--ink-muted)" }}>{t("technicalSkills")}</p>
                <div className="flex flex-wrap gap-1.5">
                  {skillList.map((s) => (
                    <Badge key={s} variant="secondary">
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </Card>
        )}

        {showEmptyState ? (
          <EmptyState
            icon={FileUp}
            title={t("importFromResume")}
            hint={t("subtitle")}
            action={
              <div className="flex flex-col items-center gap-2">
                <label className={buttonVariants({ size: "md", className: "cursor-pointer" })}>
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    onChange={handleFileUpload}
                    disabled={uploadingFile}
                    className="hidden"
                  />
                  {uploadingFile ? t("parsingFile") : t("clickToUpload")}
                </label>
                <button
                  onClick={() => setShowImport(true)}
                  className="text-xs font-medium transition-colors hover:opacity-80"
                  style={{ color: "var(--primary)" }}
                >
                  {t("pasteManually")}
                </button>
              </div>
            }
          />
        ) : (
          <>
            {/* Resume Import Section */}
            <Card className="p-[var(--space-surface-default)] space-y-4">
              <ZoneHead title={t("importFromResume")} />
              <p className="text-xs text-[var(--ink-muted)]">
                {t("importHint")}
              </p>

              {/* File upload */}
              <div>
                <label
                  className={`flex items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-4 text-sm cursor-pointer transition-colors ${
                    uploadingFile
                      ? "border-[var(--border)] bg-[var(--muted)] text-[var(--ink-muted)] cursor-wait"
                      : "border-[var(--border)] hover:border-[var(--primary)] hover:bg-[var(--muted)] text-[var(--ink-muted)]"
                  }`}
                >
                  <input
                    type="file"
                    accept=".pdf,.docx"
                    onChange={handleFileUpload}
                    disabled={uploadingFile}
                    className="hidden"
                  />
                  {uploadingFile ? (
                    <span>{t("parsingFile")}</span>
                  ) : (
                    <span>{t("clickToUpload")}</span>
                  )}
                </label>
                {uploadError && (
                  <Banner variant="danger" size="sm" className="mt-1.5">
                    {uploadError}
                  </Banner>
                )}
              </div>

              {/* Toggle for paste textarea */}
              <button
                onClick={() => setShowImport(!showImport)}
                className="text-xs font-medium transition-colors hover:opacity-80"
                style={{ color: "var(--primary)" }}
              >
                {showImport ? t("hideTextInput") : t("pasteManually")}
              </button>

              {showImport && (
                <Textarea
                  rows={8}
                  value={resumeText}
                  onChange={(e) => setResumeText(e.target.value)}
                  placeholder={t("pastePlaceholder")}
                  disabled={importStatus === "generating"}
                />
              )}

              {resumeText.trim() && (
                <div className="flex items-center gap-3">
                  <Button
                    onClick={handleImport}
                    disabled={!resumeText.trim()}
                    loading={importStatus === "generating"}
                  >
                    {importStatus === "generating" ? t("generating") : t("generateDraft")}
                  </Button>

                  <span className="text-xs text-[var(--ink-muted)]">
                    {t("charsCount", { count: resumeText.trim().length.toLocaleString() })}
                  </span>
                </div>
              )}

              {/* Clean resume preview */}
              {cleanResume?.markdown && (
                <details className="rounded-lg border border-[var(--border)] bg-[var(--muted)]">
                  <summary className="px-3 py-2 text-xs font-medium text-[var(--ink-muted)] cursor-pointer hover:text-[var(--ink-secondary)]">
                    {t("viewReconstructed")}
                  </summary>
                  <pre className="px-3 py-2 text-xs text-[var(--ink-secondary)] whitespace-pre-wrap max-h-64 overflow-y-auto border-t border-[var(--border)]">
                    {cleanResume.markdown}
                  </pre>
                </details>
              )}

              {/* Parse notes */}
              {parseNotes && (
                <div className="space-y-2">
                  {(parseNotes.assumptions ?? []).length > 0 && (
                    <Banner variant="warn" size="sm" title={t("assumptions")}>
                      {parseNotes.assumptions!.join(" | ")}
                    </Banner>
                  )}
                  {(parseNotes.missing_information ?? []).length > 0 && (
                    <Banner variant="neutral" size="sm" title={t("notFoundInResume")}>
                      {parseNotes.missing_information!.join(" | ")}
                    </Banner>
                  )}
                  {(parseNotes.low_confidence_items ?? []).length > 0 && (
                    <Banner variant="warn" size="sm" title={t("lowConfidence")}>
                      {parseNotes.low_confidence_items!.join(" | ")}
                    </Banner>
                  )}
                </div>
              )}

              {/* Extracted projects preview */}
              {draftProjects && draftProjects.length > 0 && (
                <div>
                  <p className="text-xs text-[var(--ink-muted)] mb-2 font-medium">
                    {t("extractedProjects", { count: draftProjects.length })}
                  </p>
                  <div className="space-y-1.5">
                    {(draftProjects as Array<{ title?: string; description?: string }>).map(
                      (p, i) => (
                        <Row key={i} className="px-3 py-2 text-xs text-[var(--ink-secondary)]">
                          <span className="font-medium">{p.title || t("projectFallback", { n: i + 1 })}</span>
                          {p.description && (
                            <span className="text-[var(--ink-muted)]"> — {p.description.slice(0, 120)}</span>
                          )}
                        </Row>
                      ),
                    )}
                  </div>
                </div>
              )}
            </Card>

            {/* Edit form */}
            <Card className="p-[var(--space-surface-default)]">
              <ZoneHead
                title={t("editProfile")}
                sub={
                  allProfiles.length > 1 ? (
                    <Dialog>
                      <DialogTrigger
                        disabled={saving}
                        className={buttonVariants({ variant: "ghost", size: "sm" })}
                        style={{ color: "var(--danger-fg)" }}
                      >
                        {t("deleteThisProfile")}
                      </DialogTrigger>
                      <DialogContent>
                        <DialogTitle>{t("deleteConfirmTitle")}</DialogTitle>
                        <DialogDescription>{t("deleteConfirmDescription")}</DialogDescription>
                        <div className="flex justify-end gap-2 mt-5">
                          <DialogClose className={buttonVariants({ variant: "outline", size: "md" })}>
                            {t("deleteConfirmCancel")}
                          </DialogClose>
                          <DialogClose
                            onClick={handleDeleteProfile}
                            className={buttonVariants({ variant: "destructive", size: "md" })}
                          >
                            {t("deleteConfirmButton")}
                          </DialogClose>
                        </div>
                      </DialogContent>
                    </Dialog>
                  ) : undefined
                }
              />

              <div className="space-y-5">
                <Field label={t("labelLabel")} hint={t("labelHint")}>
                  <Input value={fields.label} onChange={handleChange("label")} />
                </Field>

                <Field label={t("summaryLabel")} hint={t("summaryHint")}>
                  <Textarea rows={3} value={fields.summary} onChange={handleChange("summary")} />
                </Field>

                <Field label={t("experienceSummaryLabel")} hint={t("experienceSummaryHint")}>
                  <Textarea rows={4} value={fields.experience_summary} onChange={handleChange("experience_summary")} />
                </Field>

                <Field label={t("educationLabel")} hint={t("educationHint")}>
                  <Textarea rows={2} value={fields.education_summary} onChange={handleChange("education_summary")} />
                </Field>

                <Field label={t("yearsLabel")} hint={t("yearsHint")}>
                  <Input
                    type="number"
                    value={fields.years_experience}
                    onChange={handleChange("years_experience")}
                    className="w-28"
                  />
                </Field>

                <Field label={t("technicalSkills")} hint={t("skillsHint")}>
                  <Textarea rows={2} value={fields.technical_skills} onChange={handleChange("technical_skills")} />
                </Field>

                <Field label={t("subjectAreas")} hint={t("subjectAreasHint")}>
                  <Textarea rows={2} value={fields.subject_areas} onChange={handleChange("subject_areas")} />
                </Field>

                <Field label={t("toolsLabel")} hint={t("toolsHint")}>
                  <Textarea rows={2} value={fields.tools} onChange={handleChange("tools")} />
                </Field>
              </div>

              <div className="mt-8 pt-4 border-t border-[var(--border)] flex items-center gap-4">
                <Button onClick={importStatus === "ready" ? handleApplyAndSave : handleSave} loading={saving}>
                  {t("saveProfile")}
                </Button>
              </div>
            </Card>
          </>
        )}
      </div>
      </PageContainer>
    </div>
  );
}
