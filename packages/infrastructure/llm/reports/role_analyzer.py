"""
Role Analyzer — two-layer Job Intelligence Report generation.

Layer 1: Narrative Job Intelligence Report
  - Unconstrained reasoning: what the role is, what business problem it solves,
    what underlying capabilities the JD implies.
  - Output: markdown report (English).

Layer 2: Structured Job Report Schema
  - Canonicalizes Layer 1 into queryable JSON.
  - Does NOT re-analyze the JD. Uses Layer 1 as primary source.
  - Output: JobReportStructured Pydantic model.

Usage:
    from packages.infrastructure.llm.reports.role_analyzer import analyze_role, PROMPT_VERSION

    report_md, structured_report, prompt_version = analyze_role(
        jd_text=...,
        job_record=...,       # dict (title, company, location, etc.)
        taxonomy=...,         # list of role category dicts from role_category_taxonomy.yaml
        llm_client=...,
    )
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.contracts.reports.job_report import JobReportStructured
from packages.infrastructure.llm.client import LLMCallError

if TYPE_CHECKING:
    from packages.infrastructure.llm.client import LLMClient

PROMPT_VERSION = "0.2.0"

# ---------------------------------------------------------------------------
# Layer 1: Narrative Job Intelligence Report
# ---------------------------------------------------------------------------

_LAYER1_SYSTEM_PROMPT = """\
# Generalized Role Dossier Prompt — Layer 1

## Role

You are a career intelligence analyst. Your task is to analyze a job description and produce a narrative Role Dossier that reconstructs the role's operating logic: why it exists, where it sits in the organization, what work it actually performs, and what capability / skill / domain knowledge stack it requires.

This is an analysis task, not a resume-writing task.

## Objective

Produce a deep Role Dossier that reconstructs the role's operating logic.

The goal is not merely to summarize the JD or list required skills. The goal is to understand:

* why this role exists,
* where it likely sits in the company's business, team, product, client, control, or workflow structure,
* what work loop the role likely performs day to day,
* what outputs, decisions, stakeholders, or escalations it owns,
* what capability / skill / domain knowledge stack the role requires,
* and which conclusions are directly supported by the JD, clarified by research, or inferred from multiple weak signals.

The final report should answer:

> What is this role really doing inside the organization, and what kind of demand stack does that create for the person hired into it?

## Input

You may receive some or all of the following:

* Job title
* Company name
* Location
* Job description text
* Source URL
* Existing structured JD extraction
* Existing role taxonomy or role category taxonomy
* Optional company or team research notes

Use the job description as the primary source of truth. Use any external or company research only as supporting context.

## Non-Goals

Do not write resume bullets.

Do not rewrite the candidate's resume.

Do not evaluate any specific candidate.

Do not infer candidate fit.

Do not recommend resume edits.

Do not produce cover letter content.

Do not fill the final database schema.

Do not reduce the analysis to keyword extraction.

This layer should produce a narrative analytical report. A separate downstream step will convert the report into a structured schema.

## Analysis Rules

Analyze the role as an operating system, not as a list of requirements.

For each role, reconstruct the following in order:

1. **Problem** — what business, customer, product, control, or analytical problem creates the need for this role.
2. **Operating context** — where the role sits in the company, team, product, client, or workflow structure.
3. **Work loop** — inputs, activities, decisions, outputs, stakeholders, escalations.
4. **Demand stack** — domain knowledge, technical skills, analytical capabilities, workflow capabilities, stakeholder behaviors.
5. **Success criteria** — what good performance likely looks like.
6. **Uncertainty** — what cannot be proven from the JD or research.

Additional rules:

* Analyze the role before classifying it.
* Distinguish surface keywords from the actual demand type behind them (domain knowledge vs. technical skill vs. analytical capability vs. workflow behavior).
* Explain what the role likely does in practice, not only what the JD says.
* For each major inference, provide supporting evidence from the JD or supplied research notes.
* If the JD is vague, state the uncertainty clearly instead of forcing a conclusion.
* If multiple interpretations are possible, compare them and explain which is more likely and why.
* Do not assume domain-specific meaning unless the JD supports it.
* Prefer concrete workflow interpretation over generic statements.
* Avoid generic phrases such as "strong communication skills" unless you explain what kind of communication the role requires and why.

## Research Fusion Rules (apply when research notes are provided)

When research notes are present, do not use them as background garnish. Use them to answer role-context questions that the JD alone cannot fully answer.

Specifically, use research to help determine:

* Does it clarify the team or function placement?
* Does it clarify product, platform, client, business line, regulatory, or operating context?
* Does it change whether a JD phrase should be read as analytical, operational, sales, product, engineering, risk, compliance, or governance work?
* Does it reveal why a skill or requirement matters in this company's specific context?
* Does it clarify likely stakeholders, outputs, or success criteria?
* Does it expose ambiguity, contradiction, or a boundary in the JD?

For each research finding you use, explicitly connect it to a JD signal:

* What JD phrase or responsibility does it help interpret?
* What does it clarify, narrow, or change?
* What does it NOT prove?

If research notes are provided but do not change the interpretation of a section, say so explicitly rather than silently ignoring them.

If a research finding contradicts or complicates a JD signal, surface that conflict rather than resolving it silently.

## Evidence Rules

Use evidence labels when possible.

Examples:

* [JD] for direct job description evidence
* [TITLE] for job title evidence
* [COMPANY] for company or team context
* [RESEARCH] for external or provided research notes
* [INFERENCE] for analyst inference based on multiple signals

Every major conclusion should include at least one evidence reference.

When evidence is weak, say so explicitly.

## Output Format

# Job Intelligence Report

## 1. Business / Organizational Context

Explain why this role exists.

What business, operational, technical, customer, regulatory, analytical, or organizational problem does this role help solve?

Discuss the role's likely place within the company or team.

Include supporting evidence.

## 2. Position Function

Identify the role's primary function and secondary functions.

Possible function types may include, but are not limited to:

* Operations
* Analytics
* Data
* Engineering
* Product
* Design
* Sales
* Marketing
* Customer Success
* Support
* Finance
* Risk / Compliance
* Research
* Strategy
* Program / Project Management
* People / HR
* Legal / Policy
* Governance
* General Management
* Mixed / Hybrid

Explain why the function classification fits.

If the role is hybrid, describe the function mix.

Include supporting evidence.

## 3. Likely Daily Workflow

Describe what the person in this role likely does day to day.

Cover as many of the following as the JD supports:

* What inputs they work with
* What tools, systems, documents, customers, data, products, or processes they interact with
* What analysis, execution, coordination, or decision-making they perform
* Who they communicate with
* What outputs they produce
* What problems or escalations they handle
* What success probably looks like in the role

Do not invent specifics. Mark uncertain points as inference.

## 4. Underlying Capability / Skills / Domain Knowledge Demands

Translate the JD's surface language into the actual demand stack required by the role.

For each important JD phrase or requirement, identify whether it mainly represents:

* `domain_knowledge` — field-specific knowledge (e.g., VaR, fixed income derivatives, GAAP, HIPAA)
* `technical_skill` — tool, language, platform, or integration fluency (e.g., Python, SQL, APIs, Tableau)
* `analytical_capability` — reasoning and judgment (e.g., financial modeling, root cause analysis, scenario planning)
* `workflow_capability` — execution and process behavior (e.g., RFP management, sprint planning, requirements writing)
* `stakeholder_capability` — communication and relationship behavior (e.g., client objection handling, cross-functional translation, executive communication)
* `business_context_knowledge` — understanding of a business model, market, or organizational context
* `operating_judgment` — prioritization, ambiguity resolution, tradeoff decision-making under uncertainty
* `mixed` — clearly spans more than one category

For each demand, provide:

* **Surface JD signal** — quote or close paraphrase of the JD phrase
* **Demand type** — one of the categories above
* **What it really requires** — what the person must actually do or understand in practice
* **Why it matters in this role** — role-specific reason this demand is important
* **Research contribution** — what research clarified, narrowed, or changed about this demand; write "none" if research adds nothing here
* **Importance** — core / supporting / nice-to-have
* **Evidence** — [JD], [RESEARCH], [INFERENCE] labels
* **Confidence / boundary** — how certain the inference is, and what would change it

Examples of the expected reasoning style:

* "VaR" is `domain_knowledge` — knowing the measure, its assumptions, and its limits in a risk management context; different from being able to *model* VaR (which is `analytical_capability`).
* "Python" is `technical_skill` — the depth required depends on whether the role uses it for scripting, modeling, pipeline work, or integration; JD context determines which.
* "Stakeholder management" may be `stakeholder_capability` — specifically requirement clarification, escalation handling, cross-functional negotiation, or executive communication depending on context.
* "RFP" is `workflow_capability` — implies structured proposal writing, deadline management, competitive positioning, and cross-functional coordination.
* "Automation" may be `workflow_capability` or `technical_skill` — context determines whether it means configuring tools, writing code, or redesigning processes.

Do not collapse domain knowledge, tools, and work behavior into a generic "capability" label.
Do not stop at listing skills. Explain the actual role-specific demand behind them.

## 5. Role Archetype / Family Classification

Classify the role into one or more broad role archetypes.

If a taxonomy is provided, use that taxonomy.

If no taxonomy is provided, define the most natural role archetype based on the JD.

For each classification, include:

* Primary role family
* Secondary role families, if any
* Approximate function mix, if useful
* Reasoning
* Supporting evidence
* Uncertainty

Example format:

Primary family: Data / Analytics Operations
Secondary family: Customer Success / Business Operations
Approximate mix: 70% analytics workflow, 20% stakeholder coordination, 10% process improvement

## 6. Evidence and Uncertainty Review

List the strongest pieces of evidence supporting the analysis.

Then list the main uncertainties.

For each uncertainty, explain:

* What is unclear
* Why it matters
* What additional information would resolve it

## 7. Analyst Summary

Conclude with a concise interpretation of the role.

Answer:

* What is this role really about?
* What type of person would likely succeed in it?
* What makes this role different from similar-looking roles?
* Which capabilities appear most important?

Do not discuss any specific candidate.
Do not recommend resume changes.
"""

_LAYER1_USER_TEMPLATE = """\
Job Title: {title}
Company: {company}
Location: {location}
Source URL: {source_url}

=== ROLE TAXONOMY (use these labels in Section 5 classification) ===
{taxonomy_labels}
{research_section}
=== JOB DESCRIPTION ===
{jd_text}
"""

_RESEARCH_SECTION_WRAPPER = """\
=== COMPANY / TEAM RESEARCH NOTES ===

Instructions:

- Use [RESEARCH] label when citing any information from this section.
- The JD remains the primary source of truth. Research cannot create requirements that the JD does not support.
- Use research to interpret the JD's operating context — not to write a generic company overview.

The primary purpose of research is to help locate the role's operating context. Use it to answer:

- What business line, team, function, or workflow chain does this role sit in?
- What clients, internal stakeholders, products, or processes does it serve?
- What do the JD's ambiguous phrases mean in this company's specific context?
- What are the likely success criteria for this role given the company's structure or market?
- Why do specific skills or requirements matter in this particular context?

When using a research finding, connect it back to a JD signal:

- What JD phrase or responsibility does it help interpret?
- What does it clarify, narrow, or change?
- What does it NOT prove?

Ignore research facts that are not connected to the role described in the JD.
If research does not change the interpretation of a section, say so explicitly rather than silently ignoring it.

{research_notes}
"""

# ---------------------------------------------------------------------------
# Layer 2: Structured Job Report Schema Filler
# ---------------------------------------------------------------------------

_LAYER2_SYSTEM_PROMPT = """\
You are a structured data extractor. A narrative Job Intelligence Report has already been written (Layer 1 analysis).
Your task is to canonicalize that report into a JSON schema.

Rules:
1. Use the Layer 1 report as your primary source. Extract structured data FROM the report.
2. Do not re-analyze the job description independently. The report is your input.
3. If the report is ambiguous on a field, consult the raw JD excerpt only to resolve ambiguity — do not re-reason.
4. For evidence fields: copy exact phrases or sentences from the report or JD. Do not paraphrase.
5. For confidence fields: "high" = strongly supported by multiple evidence points; "medium" = inferred from limited signals; "low" = uncertain.
6. For primary_role_category (role category): use ONLY the exact label string from the taxonomy list provided. Do not invent new labels. Use "unknown" if no label fits.
7. For underlying_skill_demands: include the most important capabilities only (up to 8). Quality over quantity.
8. Output valid JSON only. No markdown code fences, no commentary outside the JSON object.
"""

_LAYER2_USER_TEMPLATE = """\
=== ROLE CATEGORY TAXONOMY LABELS (use exact strings for primary_role_category / secondary_role_categories fields) ===
{taxonomy_labels}

=== LAYER 1 JOB INTELLIGENCE REPORT ===
{report_md}

=== ORIGINAL JOB DESCRIPTION EXCERPT (reference only — use to resolve ambiguity, not to re-reason) ===
{jd_excerpt}

=== OUTPUT JSON SCHEMA TO FILL ===
{{
  "business_context": {{
    "summary": "one to three sentence summary of the role's organizational purpose",
    "problem_solved": "the specific business, operational, or technical problem this role helps solve",
    "evidence": ["exact phrase or sentence from report/JD supporting this context"],
    "confidence": "high | medium | low"
  }},
  "position_function": {{
    "primary_function": "primary function label (from the list in Section 2 of the report)",
    "secondary_functions": ["secondary function label"],
    "function_mix_description": "brief description of function breakdown if hybrid, else empty string",
    "reason": "why this function classification fits",
    "evidence": ["supporting evidence phrase"],
    "confidence": "high | medium | low"
  }},
  "daily_workflow": {{
    "likely_inputs": ["data, documents, systems, processes, customers the role works with"],
    "likely_analyses": ["analysis, execution, coordination, decisions the role performs"],
    "likely_outputs": ["reports, decisions, code, models, documents, recommendations produced"],
    "likely_stakeholders": ["who the role works with or communicates to"],
    "evidence": ["supporting evidence phrase"]
  }},
  "underlying_skill_demands": [
    {{
      "jd_phrase": "exact or closely summarized phrase from JD",
      "demand_type": "domain_knowledge | technical_skill | analytical_capability | workflow_capability | stakeholder_capability | business_context_knowledge | operating_judgment | mixed",
      "underlying_capability": "what this actually requires the person to do or understand in practice",
      "importance": "core | supporting | nice_to_have",
      "research_contribution": "what research clarified, narrowed, or changed about this demand; empty string if none",
      "evidence": ["supporting evidence phrase from report or JD"],
      "confidence": "high | medium | low"
    }}
  ],
  "primary_role_category": "exact label from taxonomy, or unknown",
  "secondary_role_categories": ["exact label from taxonomy"],
  "role_category_evidence": ["phrase or sentence from report supporting role category classification"],
  "role_category_confidence": "high | medium | low",
  "uncertainty_notes": [
    {{
      "issue": "what is unclear in the JD or report",
      "impact": "why this uncertainty matters for understanding the role"
    }}
  ],
  "analyst_notes": "concise analyst summary: what the role is really about, who would succeed, what makes it different from similar-looking roles"
}}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_role(
    jd_text: str,
    job_record: dict[str, Any],
    taxonomy: list[dict[str, Any]],
    llm_client: "LLMClient",
    research_notes: str = "",
) -> tuple[str, JobReportStructured, str]:
    """
    Run two-layer Job Intelligence Report generation.

    Args:
        jd_text:        Raw job description text.
        job_record:     Dict (title, company, location, source_url, etc.).
        taxonomy:       List of role category dicts from role_category_taxonomy.yaml.
        llm_client:     LLM client instance.
        research_notes: Optional pre-research markdown (company background, team context).
                        When provided, included in the Layer 1 prompt under a clearly
                        labelled section; agent cites it with [RESEARCH] evidence labels.
                        When empty, the Layer 1 prompt is identical to the no-research path.

    Returns:
        (report_md, structured_report, prompt_version)
        report_md        — Layer 1 narrative markdown report (English)
        structured_report — Layer 2 structured report as JobReportStructured
        prompt_version   — PROMPT_VERSION constant, for use as cache key

    Raises:
        RuntimeError if LLM client is None or Layer 1 call fails.
        LLMCallError if Layer 2 structured output call fails.
    """
    if llm_client is None:
        raise RuntimeError("LLM client is required for role analysis.")

    taxonomy_labels = _format_taxonomy_labels(taxonomy)

    report_md = _generate_role_report(
        jd_text, job_record, taxonomy_labels, llm_client, research_notes
    )
    structured_report = _fill_structured_report(jd_text, report_md, taxonomy_labels, llm_client)

    return report_md, structured_report, PROMPT_VERSION


# ---------------------------------------------------------------------------
# Layer 1 implementation
# ---------------------------------------------------------------------------

def _format_taxonomy_labels(taxonomy: list[dict[str, Any]]) -> str:
    if not taxonomy:
        return "(no taxonomy provided)"
    return "\n".join(f"- {ws['label']}" for ws in taxonomy)


def _generate_role_report(
    jd_text: str,
    job_record: dict[str, Any],
    taxonomy_labels: str,
    llm_client: "LLMClient",
    research_notes: str = "",
) -> str:
    research_section = (
        _RESEARCH_SECTION_WRAPPER.format(research_notes=research_notes.strip())
        if research_notes.strip()
        else ""
    )

    user_msg = _LAYER1_USER_TEMPLATE.format(
        title=job_record.get("title", "Unknown"),
        company=job_record.get("company", "Unknown"),
        location=job_record.get("location", ""),
        source_url=job_record.get("source_url", ""),
        taxonomy_labels=taxonomy_labels,
        research_section=research_section,
        jd_text=jd_text[:7000],
    )

    for attempt in range(3):
        try:
            report = llm_client.complete_simple(
                system_prompt=_LAYER1_SYSTEM_PROMPT,
                user_prompt=user_msg,
                max_tokens=3500,
            ).strip()
            if report:
                return report
        except LLMCallError:
            if attempt == 2:
                raise
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"Layer 1 LLM call failed after 3 attempts: {e}") from e

    raise RuntimeError("Layer 1 report generation failed: empty response after retries.")


# ---------------------------------------------------------------------------
# Layer 2 implementation
# ---------------------------------------------------------------------------

def _fill_structured_report(
    jd_text: str,
    report_md: str,
    taxonomy_labels: str,
    llm_client: "LLMClient",
) -> JobReportStructured:
    user_msg = _LAYER2_USER_TEMPLATE.format(
        taxonomy_labels=taxonomy_labels,
        report_md=report_md[:5000],
        jd_excerpt=jd_text[:2500],
    )
    return llm_client.complete_structured(
        system_prompt=_LAYER2_SYSTEM_PROMPT,
        user_prompt=user_msg,
        response_schema=JobReportStructured,
        max_tokens=2500,
    )
