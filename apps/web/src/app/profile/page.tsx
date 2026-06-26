"use client";

import { useEffect, useState, useCallback } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import {
  createRun,
  getProfile,
  upsertProfile,
  type ProfileRead,
  type ProfileUpdate,
} from "@/api/client";
import { pollRunUntilDone } from "@/lib/pollRun";

type FieldState = {
  summary: string;
  experience_summary: string;
  education_summary: string;
  technical_skills: string;
  subject_areas: string;
  tools: string;
  years_experience: string;
};

const EMPTY_FIELDS: FieldState = {
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

function draftToFields(d: ProfileDraft): FieldState {
  return {
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
  const getToken = useApiToken();
  const [fields, setFields] = useState<FieldState>(EMPTY_FIELDS);
  const [serverProfile, setServerProfile] = useState<ProfileRead | null>(null);
  const [profileHash, setProfileHash] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Resume import state
  const [resumeText, setResumeText] = useState("");
  const [importStatus, setImportStatus] = useState<ImportStatus>("idle");
  const [importError, setImportError] = useState<string | null>(null);
  const [parseNotes, setParseNotes] = useState<ParseNotes | null>(null);
  const [draftProjects, setDraftProjects] = useState<unknown[] | null>(null);
  const [showImport, setShowImport] = useState(false);

  const loadProfile = useCallback(async () => {
    try {
      const token = await getToken();
      const profile = await getProfile(token);
      setFields(profileToFields(profile));
      setServerProfile(profile);
      setProfileHash(profile.profile_hash);
    } catch (err: unknown) {
      if (
        err &&
        typeof err === "object" &&
        "status" in err &&
        (err as { status: number }).status === 404
      ) {
        // No profile yet
      } else {
        setErrorMsg("Failed to load profile.");
      }
    } finally {
      setLoading(false);
    }
  }, [getToken]);

  useEffect(() => {
    loadProfile();
  }, [loadProfile]);

  const handleChange =
    (key: keyof FieldState) =>
    (e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>) =>
      setFields((prev) => ({ ...prev, [key]: e.target.value }));

  const handleSave = async () => {
    setSaving(true);
    setStatus("idle");
    setErrorMsg(null);
    try {
      const token = await getToken();
      const updated = await upsertProfile(fieldsToUpdate(fields, serverProfile), token);
      setFields(profileToFields(updated));
      setServerProfile(updated);
      setProfileHash(updated.profile_hash);
      setStatus("saved");
    } catch (err: unknown) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  const handleImport = async () => {
    if (!resumeText.trim()) return;
    setImportStatus("generating");
    setImportError(null);
    setParseNotes(null);
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
      const finished = await pollRunUntilDone(run.id, token, { intervalMs: 2000, timeoutMs: 120_000 });

      if (finished.status !== "succeeded") {
        setImportStatus("error");
        setImportError(finished.error_message ?? `Import ${finished.status}`);
        return;
      }

      const summary = finished.result_summary_json as Record<string, unknown> | null;
      const draft = summary?.profile_draft as ProfileDraft | undefined;
      const notes = summary?.parse_notes as ParseNotes | undefined;

      if (!draft) {
        setImportStatus("error");
        setImportError("No profile draft returned.");
        return;
      }

      setFields(draftToFields(draft));
      setDraftProjects(draft.representative_projects ?? null);
      if (notes) setParseNotes(notes);
      setImportStatus("ready");
    } catch (err: unknown) {
      setImportStatus("error");
      setImportError(err instanceof Error ? err.message : "Import failed.");
    }
  };

  const handleApplyAndSave = async () => {
    setSaving(true);
    setStatus("idle");
    setErrorMsg(null);
    try {
      const token = await getToken();
      const payload = fieldsToUpdate(fields, serverProfile);
      if (draftProjects && draftProjects.length > 0) {
        payload.representative_projects = draftProjects;
      }
      const updated = await upsertProfile(payload, token);
      setFields(profileToFields(updated));
      setServerProfile(updated);
      setProfileHash(updated.profile_hash);
      setDraftProjects(null);
      setImportStatus("idle");
      setResumeText("");
      setParseNotes(null);
      setStatus("saved");
    } catch (err: unknown) {
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-10 text-sm text-zinc-500">Loading profile...</div>
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

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-900">Candidate Profile</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Your job-search persona — powers profile-guided discovery and fit analysis for every role.
        </p>
      </div>

      {/* Profile Summary Card */}
      {hasProfileData && (
        <div className="mb-8 rounded-xl border border-zinc-200 bg-white p-5 space-y-4">
          <div className="flex items-start justify-between gap-2">
            <h2 className="text-sm font-semibold text-zinc-700">Profile Overview</h2>
            {profileHash && (
              <span className="font-mono text-[10px] text-zinc-400 bg-zinc-100 px-1.5 py-0.5 rounded shrink-0">
                {profileHash.slice(0, 8)}
              </span>
            )}
          </div>

          {fields.years_experience && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-zinc-400 text-xs">Experience</span>
              <span className="font-semibold text-zinc-800">{fields.years_experience} years</span>
            </div>
          )}

          {subjectAreaList.length > 0 && (
            <div>
              <p className="text-xs text-zinc-400 mb-2">Subject areas</p>
              <div className="flex flex-wrap gap-1.5">
                {subjectAreaList.map((d) => (
                  <span
                    key={d}
                    className="px-2.5 py-1 rounded-full bg-indigo-50 text-indigo-700 text-[11px] font-medium border border-indigo-100"
                  >
                    {d}
                  </span>
                ))}
              </div>
            </div>
          )}

          {skillList.length > 0 && (
            <div>
              <p className="text-xs text-zinc-400 mb-2">Technical Skills</p>
              <div className="flex flex-wrap gap-1.5">
                {skillList.map((s) => (
                  <span
                    key={s}
                    className="px-2.5 py-1 rounded-full bg-zinc-100 text-zinc-600 text-[11px] font-medium"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Resume Import Section */}
      <div className="mb-8">
        <button
          onClick={() => setShowImport(!showImport)}
          className="text-sm font-medium text-indigo-600 hover:text-indigo-500 transition-colors"
        >
          {showImport ? "Hide import" : "Import from resume"}
        </button>

        {showImport && (
          <div className="mt-3 rounded-xl border border-zinc-200 bg-white p-5 space-y-4">
            <div>
              <p className="text-xs text-zinc-400 mb-1.5">
                Paste your resume text below. The system will extract a profile draft for you to
                review and edit before saving.
              </p>
              <textarea
                rows={8}
                value={resumeText}
                onChange={(e) => setResumeText(e.target.value)}
                placeholder="Paste resume text here..."
                disabled={importStatus === "generating"}
                className="w-full rounded-md border border-zinc-200 px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-indigo-400 resize-y disabled:opacity-50"
              />
            </div>

            <div className="flex items-center gap-3">
              <button
                onClick={handleImport}
                disabled={!resumeText.trim() || importStatus === "generating"}
                className="px-4 py-2 rounded-md bg-zinc-800 text-white text-sm font-medium hover:bg-zinc-700 disabled:opacity-50 transition-colors"
              >
                {importStatus === "generating" ? "Generating..." : "Generate profile draft"}
              </button>

              {importStatus === "ready" && (
                <span className="text-sm text-emerald-600">
                  Draft loaded into form below. Review and save.
                </span>
              )}
              {importStatus === "error" && (
                <span className="text-sm text-rose-600">{importError ?? "Import failed."}</span>
              )}
            </div>

            {/* Parse notes */}
            {parseNotes && (
              <div className="space-y-2">
                {(parseNotes.assumptions ?? []).length > 0 && (
                  <div className="text-xs text-amber-700 bg-amber-50 rounded-md px-3 py-2">
                    <span className="font-medium">Assumptions: </span>
                    {parseNotes.assumptions!.join(" | ")}
                  </div>
                )}
                {(parseNotes.missing_information ?? []).length > 0 && (
                  <div className="text-xs text-zinc-500 bg-zinc-50 rounded-md px-3 py-2">
                    <span className="font-medium">Not found in resume: </span>
                    {parseNotes.missing_information!.join(" | ")}
                  </div>
                )}
                {(parseNotes.low_confidence_items ?? []).length > 0 && (
                  <div className="text-xs text-amber-700 bg-amber-50 rounded-md px-3 py-2">
                    <span className="font-medium">Low confidence: </span>
                    {parseNotes.low_confidence_items!.join(" | ")}
                  </div>
                )}
              </div>
            )}

            {/* Extracted projects preview */}
            {draftProjects && draftProjects.length > 0 && (
              <div>
                <p className="text-xs text-zinc-500 mb-2 font-medium">
                  Extracted projects ({draftProjects.length}) — will be saved with profile
                </p>
                <div className="space-y-1.5">
                  {(draftProjects as Array<{ title?: string; description?: string }>).map(
                    (p, i) => (
                      <div key={i} className="text-xs text-zinc-600 bg-zinc-50 rounded px-3 py-2">
                        <span className="font-medium">{p.title || `Project ${i + 1}`}</span>
                        {p.description && (
                          <span className="text-zinc-400"> — {p.description.slice(0, 120)}</span>
                        )}
                      </div>
                    ),
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Edit form */}
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-zinc-700">Edit Profile</h2>
      </div>

      <div className="space-y-5">
        <Field
          label="Professional Summary"
          hint="e.g. Risk analytics professional with 4 years in model validation and market risk"
          value={fields.summary}
          onChange={handleChange("summary")}
          rows={3}
        />

        <Field
          label="Experience Summary"
          hint="Brief narrative of work history most relevant to job discovery"
          value={fields.experience_summary}
          onChange={handleChange("experience_summary")}
          rows={4}
        />

        <Field
          label="Education"
          hint="e.g. BS Computer Science, Stanford University"
          value={fields.education_summary}
          onChange={handleChange("education_summary")}
          rows={2}
        />

        <TextInput
          label="Years of Experience"
          hint="Total years of professional experience"
          type="number"
          value={fields.years_experience}
          onChange={handleChange("years_experience")}
        />

        <Field
          label="Technical Skills"
          hint="Comma-separated — e.g. Python, SQL, forecasting, experimentation, API integration"
          value={fields.technical_skills}
          onChange={handleChange("technical_skills")}
          rows={2}
        />

        <Field
          label="Subject areas"
          hint="Comma-separated — e.g. product management, market risk, clinical trials, fixed income"
          value={fields.subject_areas}
          onChange={handleChange("subject_areas")}
          rows={2}
        />

        <Field
          label="Tools"
          hint="Comma-separated — e.g. Jira, Salesforce, Figma, Tableau, GitHub, Excel"
          value={fields.tools}
          onChange={handleChange("tools")}
          rows={2}
        />
      </div>

      <div className="mt-8 flex items-center gap-4">
        <button
          onClick={importStatus === "ready" ? handleApplyAndSave : handleSave}
          disabled={saving}
          className="px-4 py-2 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving..." : "Save Profile"}
        </button>
        {status === "saved" && (
          <span className="text-sm text-emerald-600">Profile saved.</span>
        )}
        {status === "error" && (
          <span className="text-sm text-rose-600">{errorMsg ?? "Save failed."}</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function Field({
  label,
  hint,
  value,
  onChange,
  rows = 3,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  rows?: number;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-zinc-700 mb-1">{label}</label>
      <p className="text-xs text-zinc-400 mb-1.5">{hint}</p>
      <textarea
        rows={rows}
        value={value}
        onChange={onChange}
        className="w-full rounded-md border border-zinc-200 px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-indigo-400 resize-y"
      />
    </div>
  );
}

function TextInput({
  label,
  hint,
  type = "text",
  value,
  onChange,
}: {
  label: string;
  hint: string;
  type?: string;
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-zinc-700 mb-1">{label}</label>
      <p className="text-xs text-zinc-400 mb-1.5">{hint}</p>
      <input
        type={type}
        value={value}
        onChange={onChange}
        className="w-48 rounded-md border border-zinc-200 px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
      />
    </div>
  );
}
