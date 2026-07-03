"""
Standalone, read-only analysis script — NOT wired into the pipeline.

Feeds the prototype investigation transcripts (from prototype_story_investigation.py)
through the EXISTING, unmodified _step_structure_stories() in story_bank_build.py,
to see what the current structuring step produces from this new-style transcript.
Does not persist anything to the DB, does not modify any production code.
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "/app")

from apps.worker.tasks.story_bank_build import _step_structure_stories  # noqa: E402
from packages.contracts.reports.candidate_story import InvestigationTranscript  # noqa: E402


def main() -> None:
    transcript_path = sys.argv[1] if len(sys.argv) > 1 else "/tmp/prototype_transcripts.json"
    input_json_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/prototype_input.json"

    with open(transcript_path) as f:
        transcript = InvestigationTranscript.model_validate_json(f.read())

    with open(input_json_path) as f:
        payload = json.load(f)
    structured_resume = payload["payload"]["structured_resume"]

    stories = _step_structure_stories(structured_resume, transcript)

    out = [s.model_dump() for s in stories]
    with open("/tmp/prototype_structured_stories.json", "w") as f:
        json.dump(out, f, indent=2)

    print(f"\nProduced {len(stories)} stories\n")
    for s in stories:
        types = [e.evidence_type for e in s.evidence_items]
        print(f"=== {s.story_id} ({s.experience_ref}) ===")
        print(f"evidence types: {types}")
        print(f"candidate_questions: {len(s.candidate_questions)}")
        print(f"do_not_claim: {len(s.do_not_claim)}")
        print(f"research_basis: {s.research_basis}")
        print()


if __name__ == "__main__":
    main()
