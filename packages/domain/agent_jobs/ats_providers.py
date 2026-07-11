"""
Static ATS provider registry — platform knowledge about how to interact with
each ATS vendor's public job board API.

This module is pure domain logic: no DB, no HTTP, no IO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ATSProviderSpec:
    provider: str
    api_url_template: str
    careers_url_template: str
    token_patterns: tuple[re.Pattern[str], ...] = field(default_factory=tuple)

    def api_url(self, token: str) -> str:
        return self.api_url_template.format(token=token)

    def careers_url(self, token: str) -> str:
        return self.careers_url_template.format(token=token)


ATS_PROVIDERS: dict[str, ATSProviderSpec] = {
    "greenhouse": ATSProviderSpec(
        provider="greenhouse",
        api_url_template="https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
        careers_url_template="https://boards.greenhouse.io/{token}",
        token_patterns=(
            re.compile(r"boards\.greenhouse\.io/(?P<token>[a-z0-9_-]+)", re.I),
            re.compile(r"job-boards\.greenhouse\.io/(?P<token>[a-z0-9_-]+)", re.I),
            re.compile(r"boards-api\.greenhouse\.io/v1/boards/(?P<token>[a-z0-9_-]+)", re.I),
        ),
    ),
    "lever": ATSProviderSpec(
        provider="lever",
        api_url_template="https://api.lever.co/v0/postings/{token}",
        careers_url_template="https://jobs.lever.co/{token}",
        token_patterns=(
            re.compile(r"jobs\.lever\.co/(?P<token>[a-z0-9_-]+)", re.I),
            re.compile(r"api\.lever\.co/v0/postings/(?P<token>[a-z0-9_-]+)", re.I),
        ),
    ),
    "ashby": ATSProviderSpec(
        provider="ashby",
        api_url_template="https://api.ashbyhq.com/posting-api/job-board/{token}",
        careers_url_template="https://jobs.ashbyhq.com/{token}",
        token_patterns=(
            re.compile(r"jobs\.ashbyhq\.com/(?P<token>[a-z0-9_-]+)", re.I),
            re.compile(r"api\.ashbyhq\.com/posting-api/job-board/(?P<token>[a-z0-9_-]+)", re.I),
        ),
    ),
}


def extract_board_info(url: str) -> tuple[str, str] | None:
    """Extract (provider, board_token) from a URL, or None if not an ATS board."""
    for provider, spec in ATS_PROVIDERS.items():
        for pat in spec.token_patterns:
            m = pat.search(url)
            if m:
                return provider, m.group("token").lower()
    return None


def build_api_url(provider: str, token: str) -> str | None:
    spec = ATS_PROVIDERS.get(provider)
    if not spec:
        return None
    return spec.api_url(token)


def build_careers_url(provider: str, token: str) -> str | None:
    spec = ATS_PROVIDERS.get(provider)
    if not spec:
        return None
    return spec.careers_url(token)


@dataclass(frozen=True)
class BoardJob:
    """Job record parsed from an ATS board API response."""
    url: str
    title: str
    company: str
    location: str | None = None
    jd_html: str | None = None
    jd_plain: str | None = None


def _strip_html(html: str) -> str:
    """HTML → plain text for JD content."""
    import html as _html_mod
    import re as _re
    text = _html_mod.unescape(html)
    text = _re.sub(r"<br\s*/?>", "\n", text)
    text = _re.sub(r"</(p|div|li|h[1-6])>", "\n", text)
    text = _re.sub(r"<[^>]+>", "", text)
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_board_response(provider: str, data: object) -> list[BoardJob]:
    """Parse ATS API JSON response into a list of BoardJob records."""
    if provider == "greenhouse":
        return _parse_greenhouse(data)
    if provider == "lever":
        return _parse_lever(data)
    if provider == "ashby":
        return _parse_ashby(data)
    return []


def _parse_greenhouse(data: object) -> list[BoardJob]:
    if not isinstance(data, dict):
        return []
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        return []
    result = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        url = j.get("absolute_url", "")
        if not url:
            continue
        loc = j.get("location")
        content_html = j.get("content") or ""
        result.append(BoardJob(
            url=url,
            title=j.get("title", ""),
            company=(j.get("company_name") or "").strip(),
            location=loc.get("name") if isinstance(loc, dict) else None,
            jd_html=content_html or None,
            jd_plain=_strip_html(content_html) if content_html else None,
        ))
    return result


def _parse_lever(data: object) -> list[BoardJob]:
    if not isinstance(data, list):
        return []
    result = []
    for j in data:
        if not isinstance(j, dict):
            continue
        url = j.get("hostedUrl", "")
        if not url:
            continue
        cats = j.get("categories", {})
        desc_plain = j.get("descriptionPlain") or ""
        desc_html = j.get("description") or ""
        result.append(BoardJob(
            url=url,
            title=j.get("text", ""),
            company="",
            location=cats.get("location") if isinstance(cats, dict) else None,
            jd_html=desc_html or None,
            jd_plain=desc_plain or (_strip_html(desc_html) if desc_html else None),
        ))
    return result


def _parse_ashby(data: object) -> list[BoardJob]:
    if not isinstance(data, dict):
        return []
    jobs = data.get("jobs")
    if not isinstance(jobs, list):
        return []
    result = []
    for j in jobs:
        if not isinstance(j, dict):
            continue
        url = j.get("jobUrl", "")
        if not url:
            continue
        desc_plain = j.get("descriptionPlain") or ""
        desc_html = j.get("descriptionHtml") or ""
        result.append(BoardJob(
            url=url,
            title=j.get("title", ""),
            company="",
            location=j.get("location") or None,
            jd_html=desc_html or None,
            jd_plain=desc_plain or (_strip_html(desc_html) if desc_html else None),
        ))
    return result
