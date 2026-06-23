"use client";

import { useEffect, useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { getProfile, upsertProfile, type ProfileRead, type ProfileUpdate } from "@/api/client";

type FieldState = {
  summary: string;
  experience_summary: string;
  education_summary: string;
  technical_skills: string; // comma-separated in the textarea
  domain_areas: string;     // comma-separated in the textarea
  years_of_experience: string;
};

const EMPTY_FIELDS: FieldState = {
  summary: "",
  experience_summary: "",
  education_summary: "",
  technical_skills: "",
  domain_areas: "",
  years_of_experience: "",
};

function profileToFields(p: ProfileRead): FieldState {
  return {
    summary: p.summary ?? "",
    experience_summary: p.experience_summary ?? "",
    education_summary: p.education_summary ?? "",
    technical_skills: (p.technical_skills ?? []).join(", "),
    domain_areas: (p.domain_areas ?? []).join(", "),
    years_of_experience: p.years_of_experience != null ? String(p.years_of_experience) : "",
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
    domain_areas: parseList(f.domain_areas).length ? parseList(f.domain_areas) : null,
    years_of_experience: f.years_of_experience ? parseInt(f.years_of_experience, 10) || null : null,
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

  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-zinc-900">Candidate Profile</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Your profile is used for profile-guided job discovery and fit analysis.
          {profileHash && (
            <span className="ml-2 font-mono text-xs text-zinc-400">hash: {profileHash.slice(0, 8)}</span>
          )}
        </p>
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
          value={fields.years_of_experience}
          onChange={handleChange("years_of_experience")}
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
          value={fields.domain_areas}
          onChange={handleChange("domain_areas")}
          rows={2}
        />
      </div>

      <div className="mt-8 flex items-center gap-4">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-4 py-2 rounded-md bg-zinc-900 text-white text-sm font-medium hover:bg-zinc-700 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving…" : "Save Profile"}
        </button>
        {status === "saved" && (
          <span className="text-sm text-green-600">Profile saved.</span>
        )}
        {status === "error" && (
          <span className="text-sm text-red-600">{errorMsg ?? "Save failed."}</span>
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
        className="w-full rounded-md border border-zinc-200 px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400 resize-y"
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
        className="w-48 rounded-md border border-zinc-200 px-3 py-2 text-sm text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400"
      />
    </div>
  );
}
