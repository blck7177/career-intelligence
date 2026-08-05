"""Canonical URL normalization for job-posting dedup.

``jobs.canonical_url`` is a UNIQUE column and the *only* dedup key shared by
every ingest path (agent discovery, board sync, manual import). Normalizing it
consistently before both the ``get_by_canonical_url`` lookup and the write is
what lets the same posting discovered via different referrers collapse to one
row instead of accumulating duplicates.

Design rule — normalization is deliberately asymmetric: leaving two rows that
are really the same job (a stray tracking param we didn't recognize slips
through) is cheap and recoverable; collapsing two genuinely different jobs into
one canonical_url is irreversible data loss. So this is a *strip-list*, not a
keep-list: we remove only query params known to be tracking / referrer / search
context, and keep everything else — including any param we don't recognize,
which might be a job identifier.

A keep-list would be the dangerous inversion: a job-id param we forgot to list
would silently merge distinct postings. These real production canonical_urls
are exactly why — the job id lives *entirely* in the query string:

    https://www.numerix.com/numerix-job-opportunities?gh_jid=5062846008   (+13
        more, identical path, distinct gh_jid — dropping gh_jid merges 14 jobs)
    https://www.indeed.com/viewjob?jk=09722b2f9935b99d   (job key in jk)

while these must dedup to the same row (same path, tracking-only query):

    .../job/549795985226?ref=modus.news
    .../job/549795893203?domain=morganstanley.com&source=LinkedIn&urlHash=4xus
    .../job/210753962?gh_src=Getro+Community+job+board
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query params known to carry tracking / referrer / search-context noise rather
# than job identity. Compared case-insensitively. Everything NOT listed here is
# kept — see the module docstring for why the default must be "keep".
_STRIP_PARAMS = frozenset(
    {
        "ref",
        "src",
        "source",
        "gh_src",  # Greenhouse referrer — NB distinct from gh_jid (job id, kept)
        "domain",
        "microsite",
        "keyword",
        "mode",
        "partner",
        "jvid",
        "jr_id",  # eightfold referrer/session id (same value across distinct jobs)
        "urlhash",
        "q",
        "sortby",
        "page",
        "lastselectedfacet",
        "selectedlocationsfacet",
        "jobfamilygroup",
        "usemylastapplication",
        "embed",
        "iis",  # LinkedIn "in it source" referrer (?iis=LinkedIn) — seen on
        #         careers.cobank.com and oraclecloud CandidateExperience URLs
        "iisn",  # its companion source-name (?iis=Job+Boards&iisn=Indeed),
        #          seen on higher.gs.com
    }
)

# Param-name prefixes to strip (utm_source, utm_medium, ... and bare "utm").
_STRIP_PREFIXES = ("utm_", "utm")

# Eightfold-family path shape: /careers/job/<numeric id> optionally followed by
# a "-<title-slug>" that some referrers append and others don't. The id alone
# is the posting identity; the slug is decoration that varies by source. A real
# dup pair proved it:
#     careers.newyorklife.com/careers/job/39995361-senior-associate-model-...
#     careers.newyorklife.com/careers/job/39995361
# Scoped to the exact "/careers/job/<id>-<slug>" shape so this can only ever
# merge URLs sharing the same numeric id on the same host — same-id-different-
# job on one host is not a real ATS layout, so the asymmetry rule holds.
_CAREERS_JOB_SLUG_RE = re.compile(r"^(?P<keep>/careers/job/\d{6,})-[^/]+$")


def _is_tracking_param(name: str) -> bool:
    key = name.lower()
    if key in _STRIP_PARAMS:
        return True
    return any(key == p or key.startswith(p) for p in _STRIP_PREFIXES)


def normalize_job_url(url: str) -> str:
    """Return a canonical form of a job-posting URL for dedup.

    Lowercases scheme and host, drops the fragment, removes known tracking
    query params (keeping all others), and sorts the surviving params for
    stability. Non-http(s) or unparseable input is returned unchanged — URL
    validation stays the caller's job; this only canonicalizes.
    """
    if not isinstance(url, str):
        return url
    stripped = url.strip()
    if not stripped.lower().startswith(("http://", "https://")):
        return stripped

    try:
        parts = urlsplit(stripped)
    except ValueError:
        return stripped

    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(k)
    ]
    kept.sort()
    query = urlencode(kept)

    path = parts.path
    slug_match = _CAREERS_JOB_SLUG_RE.match(path)
    if slug_match:
        path = slug_match.group("keep")

    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, query, "")
    )
