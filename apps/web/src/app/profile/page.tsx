"use client";

import { useEffect, useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { getProfile, upsertProfile, type ProfileRead, type ProfileUpdate } from "@/api/client";

// FieldState mirrors the editable subset of ProfileRead using string values
// for textarea/input compatibility.
type FieldState = {
  summary: string;
  experience_summary: string;
  education_summary: string;
  technical_skills: string;   // comma-separated
  domain_experience: string;  // comma-separated — matches backend field
  years_experience: string;   // matches backend field
};

const EMPTY_FIELDS: FieldState = {
  summary: "",
  experience_summary: "",
  education_summary: "",
  technical_skills: "",
  domain_experience: "",
  years_experience: "",
};

function profileToFields(p: ProfileRead): FieldState {
  return {
    summary: p.summary ?? "",
    experience_summary: p.experience_summary ?? "",
    education_summary: p.education_summary ?? "",
    technical_skills: ((p.technical_skills ?? []) as string[]).join(", "),
    domain_experience: ((p.domain_experience ?? []) as string[]).join(", "),
    years_experience: p.years_experience != null ? String(p.years_experience) : "",
  };
}

function fieldsToUpdate(f: FieldState): ProfileUpdate {
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
    domain_experience: parseList(f.domain_experience).length ? parseList(f.domain_experience) : null,
    years_experience: f.years_experience ? parseInt(f.years_experience, 10) || null : null,
  };
}

export default function ProfilePage() {
  const getToken = useApiToken();
  const [fields, setFields] = useState<FieldState>(EMPTY_FIELDS);
  const [profileHash, setProfileHash] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const token = await getToken();
        const profile = await getProfile(token);
        setFields(profileToFields(profile));
        setProfileHash(profile.profile_hash);
      } catch (err: unknown) {
        if (err && typeof err === "object" && "status" in err && (err as { status: number }).status === 404) {
          // No profile yet — leave defaults
        } else {
          setErrorMsg("Failed to load profile.");
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [getToken]);

  const handleChange = (key: keyof FieldState) => (
    e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>
  ) => setFields((prev) => ({ ...prev, [key]: e.target.value }));

  const handleSave = async () => {
    setSaving(true);
    setStatus("idle");
    setErrorMsg(null);
    try {
      const token = await getToken();
      const updated = await upsertProfile(fieldsToUpdate(fields), token);
      setFields(profileToFields(updated));
      setProfileHash(updated.profile_hash);
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
      <div className="max-w-2xl mx-auto px-4 py-10 text-sm text-zinc-500">Loading profile…</div>
    );
  }

  const domainList = fields.domain_experience
    .split(",")
    .map((d) => d.trim())
    .filter(Boolean);
  const skillList = fields.technical_skills
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const hasProfileData =
    profileHash && (domainList.length > 0 || skillList.length > 0 || fields.years_experience);

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

          {domainList.length > 0 && (
            <div>
              <p className="text-xs text-zinc-400 mb-2">Domains</p>
              <div className="flex flex-wrap gap-1.5">
                {domainList.map((d) => (
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
          hint="e.g. MS Financial Engineering, Columbia University"
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
          hint="Comma-separated — e.g. Python, R, VaR, stress testing, scenario analysis"
          value={fields.technical_skills}
          onChange={handleChange("technical_skills")}
          rows={2}
        />

        <Field
          label="Domain Areas"
          hint="Comma-separated — e.g. market risk, model risk, credit risk, PPNR"
          value={fields.domain_experience}
          onChange={handleChange("domain_experience")}
          rows={2}
        />
      </div>

      <div className="mt-8 flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 rounded-md bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-500 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving…" : "Save Profile"}
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
