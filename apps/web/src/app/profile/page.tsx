"use client";

import { useEffect, useState } from "react";
import { useApiToken } from "@/hooks/useApiToken";
import { getProfile, upsertProfile, type ProfileRead, type ProfileUpdate } from "@/api/client";

const PROJECTS_PLACEHOLDER = `[
  {
    "title": "VaR Model Validation",
    "description": "Led independent validation of historical simulation VaR model",
    "skills_used": ["Python", "statistics", "VaR"],
    "quantified_impact": "Cleared regulatory review, reduced model risk flag by 30%"
  }
]`;

type FieldState = {
  summary: string;
  experience_summary: string;
  education_summary: string;
  years_experience: string;
  technical_skills: string;    // comma-separated
  domain_experience: string;   // comma-separated
  finance_domains: string;     // comma-separated
  tools: string;               // comma-separated
  representative_projects: string;  // JSON textarea
};

const EMPTY_FIELDS: FieldState = {
  summary: "",
  experience_summary: "",
  education_summary: "",
  years_experience: "",
  technical_skills: "",
  domain_experience: "",
  finance_domains: "",
  tools: "",
  representative_projects: "",
};

function profileToFields(p: ProfileRead): FieldState {
  let projectsStr = "";
  if (p.representative_projects && (p.representative_projects as unknown[]).length > 0) {
    try {
      projectsStr = JSON.stringify(p.representative_projects, null, 2);
    } catch {
      projectsStr = "";
    }
  }
  return {
    summary: p.summary ?? "",
    experience_summary: p.experience_summary ?? "",
    education_summary: p.education_summary ?? "",
    years_experience: p.years_experience != null ? String(p.years_experience) : "",
    technical_skills: (p.technical_skills ?? []).join(", "),
    domain_experience: (p.domain_experience ?? []).join(", "),
    finance_domains: (p.finance_domains ?? []).join(", "),
    tools: (p.tools ?? []).join(", "),
    representative_projects: projectsStr,
  };
}

function parseList(s: string): string[] {
  return s.split(",").map((x) => x.trim()).filter(Boolean);
}

function fieldsToUpdate(f: FieldState): ProfileUpdate | null {
  let representative_projects: unknown[] | null = null;
  if (f.representative_projects.trim()) {
    try {
      const parsed = JSON.parse(f.representative_projects);
      if (!Array.isArray(parsed)) return null;
      representative_projects = parsed;
    } catch {
      return null;
    }
  } else {
    representative_projects = [];
  }

  return {
    summary: f.summary || null,
    experience_summary: f.experience_summary || null,
    education_summary: f.education_summary || null,
    years_experience: f.years_experience ? parseInt(f.years_experience, 10) || null : null,
    technical_skills: parseList(f.technical_skills).length ? parseList(f.technical_skills) : null,
    domain_experience: parseList(f.domain_experience).length ? parseList(f.domain_experience) : null,
    finance_domains: parseList(f.finance_domains).length ? parseList(f.finance_domains) : null,
    tools: parseList(f.tools).length ? parseList(f.tools) : null,
    representative_projects: representative_projects as Record<string, unknown>[] | null,
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
  const [projectsError, setProjectsError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const token = await getToken();
        const profile = await getProfile(token);
        setFields(profileToFields(profile));
        setProfileHash(profile.profile_hash);
      } catch (err: unknown) {
        setErrorMsg("Failed to load profile.");
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [getToken]);

  const handleChange = (key: keyof FieldState) => (
    e: React.ChangeEvent<HTMLTextAreaElement | HTMLInputElement>
  ) => {
    setFields((prev) => ({ ...prev, [key]: e.target.value }));
    if (key === "representative_projects") setProjectsError(null);
  };

  const handleSave = async () => {
    const update = fieldsToUpdate(fields);
    if (update === null) {
      setProjectsError("Invalid JSON — check for missing commas, quotes, or brackets.");
      return;
    }
    setSaving(true);
    setStatus("idle");
    setErrorMsg(null);
    setProjectsError(null);
    try {
      const token = await getToken();
      const updated = await upsertProfile(update, token);
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
          Used for profile-guided job discovery and fit report generation.
          {profileHash && (
            <span className="ml-2 font-mono text-xs text-zinc-400">hash: {profileHash.slice(0, 8)}</span>
          )}
        </p>
      </div>

      <div className="space-y-5">
        <Field
          label="Professional Summary"
          hint='One to three sentences: current role, domain, and focus. e.g. "VP Risk at a bulge bracket bank with 5 years in market risk analytics and model validation."'
          value={fields.summary}
          onChange={handleChange("summary")}
          rows={3}
        />

        <Field
          label="Experience Summary"
          hint="Broader career narrative — firms, roles, key responsibilities. Used to enrich discovery searches."
          value={fields.experience_summary}
          onChange={handleChange("experience_summary")}
          rows={4}
        />

        <Field
          label="Education"
          hint='e.g. "MS Financial Engineering, Columbia University"'
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
          label="Technical Skills / Methods"
          hint="Comma-separated. Include both tools and quantitative methods — e.g. Python, SQL, VaR, stress testing, Monte Carlo, Excel"
          value={fields.technical_skills}
          onChange={handleChange("technical_skills")}
          rows={2}
        />

        <Field
          label="Domain Experience"
          hint="Comma-separated functional areas — e.g. market risk, model validation, credit risk, PPNR, exposure management"
          value={fields.domain_experience}
          onChange={handleChange("domain_experience")}
          rows={2}
        />

        <Field
          label="Finance Domains"
          hint="Comma-separated asset classes and product knowledge — e.g. derivatives, fixed income, structured products, equities"
          value={fields.finance_domains}
          onChange={handleChange("finance_domains")}
          rows={2}
        />

        <Field
          label="Tools & Platforms"
          hint="Comma-separated — e.g. Bloomberg, Murex, Quantlib, Tableau, PowerBI"
          value={fields.tools}
          onChange={handleChange("tools")}
          rows={2}
        />

        <div>
          <label className="block text-sm font-medium text-zinc-700 mb-1">
            Representative Projects
          </label>
          <p className="text-xs text-zinc-400 mb-1.5">
            JSON array. Each entry: title, description, skills_used (array), quantified_impact.
            These are cited as evidence in fit report analysis.
          </p>
          <textarea
            rows={8}
            value={fields.representative_projects}
            onChange={handleChange("representative_projects")}
            placeholder={PROJECTS_PLACEHOLDER}
            className="w-full rounded-md border border-zinc-200 px-3 py-2 text-xs font-mono text-zinc-900 placeholder-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-400 resize-y"
          />
          {projectsError && (
            <p className="text-xs text-rose-600 mt-1">{projectsError}</p>
          )}
        </div>
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
