#!/usr/bin/env python3
"""
Backfill jd_structured for existing jobs that have jd_text but no extraction.

Usage:
    python scripts/backfill_jd_structured.py [--dry-run]

Requires OPENAI_API_KEY and DATABASE_URL environment variables.
"""

from __future__ import annotations

import argparse
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from packages.infrastructure.db.session import get_session
from packages.infrastructure.db.repositories import JobRepository
from packages.infrastructure.llm.client import get_llm_client
from packages.infrastructure.llm.jd_extractor import extract_jd_fields

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Backfill jd_structured for existing jobs")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    llm_client = get_llm_client()
    processed = 0
    skipped = 0
    failed = 0

    with get_session() as session:
        job_repo = JobRepository(session)

        from sqlalchemy import select, text
        from packages.infrastructure.db.models import Job

        stmt = select(Job).where(
            Job.jd_text.isnot(None),
            Job.jd_text != "",
        ).order_by(Job.created_at)

        jobs = session.execute(stmt).scalars().all()
        logger.info("Found %d jobs with jd_text", len(jobs))

        for job in jobs:
            existing = (job.raw_payload_json or {}).get("jd_structured")
            if isinstance(existing, dict) and "_extraction_error" not in existing:
                has_content = any(
                    existing.get(k)
                    for k in ("responsibilities", "required_skills", "likely_tasks")
                )
                if has_content:
                    logger.info("SKIP %s — already has good extraction: %s", job.id, job.title)
                    skipped += 1
                    continue

            logger.info("PROCESS %s — %s (%s)", job.id, job.title, job.company)

            if args.dry_run:
                processed += 1
                continue

            try:
                extraction = extract_jd_fields(
                    jd_text=job.jd_text,
                    company=job.company,
                    title=job.title,
                    location=job.location or "",
                    llm_client=llm_client,
                )

                if "_extraction_error" in extraction:
                    logger.warning("  extraction error: %s", extraction["_extraction_error"])
                    failed += 1
                    continue

                payload = dict(job.raw_payload_json or {})
                payload["jd_structured"] = extraction
                job.raw_payload_json = payload
                session.flush()

                resp_count = len(extraction.get("responsibilities", []))
                skills_count = len(extraction.get("required_skills", []))
                logger.info("  OK — %d responsibilities, %d required_skills", resp_count, skills_count)
                processed += 1

            except Exception as exc:
                logger.error("  FAILED: %s", exc)
                failed += 1

        if not args.dry_run:
            session.commit()
            logger.info("Committed all changes")

    logger.info(
        "Done: processed=%d skipped=%d failed=%d%s",
        processed, skipped, failed,
        " (DRY RUN)" if args.dry_run else "",
    )


if __name__ == "__main__":
    main()
