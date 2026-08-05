"""Tests for canonical URL normalization.

Cases are drawn from real production canonical_urls (the 48 rows that carried a
query string), so this doubles as a regression guard for the dedup key.
"""

from packages.domain.agent_jobs.url_normalize import normalize_job_url


class TestJobIdParamsSurvive:
    """The dangerous direction: a job-id-bearing param must never be stripped,
    or distinct postings collapse into one canonical_url (irreversible)."""

    def test_gh_jid_is_kept(self):
        # numerix: identical path, job id lives entirely in gh_jid
        url = "https://www.numerix.com/numerix-job-opportunities?gh_jid=5062846008"
        assert "gh_jid=5062846008" in normalize_job_url(url)

    def test_distinct_gh_jids_stay_distinct(self):
        base = "https://www.numerix.com/numerix-job-opportunities?gh_jid="
        a = normalize_job_url(base + "5062846008")
        b = normalize_job_url(base + "5175455008")
        assert a != b

    def test_indeed_jk_is_kept(self):
        url = "https://www.indeed.com/viewjob?jk=09722b2f9935b99d"
        assert normalize_job_url(url) == url

    def test_unrecognized_param_is_kept(self):
        # Default must be "keep" — an unknown param might be a job identifier.
        url = "https://example.com/job?somethingNew=abc123"
        assert "somethingNew=abc123" in normalize_job_url(url)


class TestTrackingParamsStripped:
    """The safe direction: same posting via different referrers must dedup."""

    def test_ref_stripped(self):
        url = "https://jobs.ashbyhq.com/langchain/f07c1416?ref=levels.fyi&src=levels.fyi"
        assert normalize_job_url(url) == "https://jobs.ashbyhq.com/langchain/f07c1416"

    def test_gh_src_stripped_but_not_gh_jid(self):
        url = "https://ms.wd5.myworkdayjobs.com/External/job/x_PT-JR028257?gh_src=AnitaB.org+job+board"
        assert normalize_job_url(url) == "https://ms.wd5.myworkdayjobs.com/External/job/x_PT-JR028257"

    def test_domain_source_urlhash_stripped(self):
        url = "https://morganstanley.eightfold.ai/careers/job/549795893203?domain=morganstanley.com&source=LinkedIn&urlHash=4xus"
        assert normalize_job_url(url) == "https://morganstanley.eightfold.ai/careers/job/549795893203"

    def test_utm_prefix_stripped(self):
        url = "https://example.com/job/1?utm_source=x&utm_medium=y&utm=undefined"
        assert normalize_job_url(url) == "https://example.com/job/1"

    def test_iis_stripped(self):
        # LinkedIn referrer param, seen on cobank + oraclecloud imports
        url = "https://careers.cobank.com/jobs/7863?iis=LinkedIn"
        assert normalize_job_url(url) == "https://careers.cobank.com/jobs/7863"

    def test_same_job_different_referrers_dedup(self):
        a = normalize_job_url("https://co.com/job/1?source=LinkedIn")
        b = normalize_job_url("https://co.com/job/1?ref=modus.news")
        c = normalize_job_url("https://co.com/job/1")
        assert a == b == c


class TestStructuralNormalization:
    def test_host_lowercased(self):
        url = "https://Jobs.AshbyHQ.com/co/abc"
        assert normalize_job_url(url) == "https://jobs.ashbyhq.com/co/abc"

    def test_fragment_dropped(self):
        assert normalize_job_url("https://co.com/job/1#section") == "https://co.com/job/1"

    def test_surviving_params_sorted(self):
        # order-independent so the same job+params in either order dedups
        a = normalize_job_url("https://co.com/j?gh_jid=1&other=2")
        b = normalize_job_url("https://co.com/j?other=2&gh_jid=1")
        assert a == b

    def test_no_query_unchanged(self):
        url = "https://jobs.lever.co/company/uuid-here"
        assert normalize_job_url(url) == url

    def test_careers_job_slug_stripped(self):
        # Eightfold-family /careers/job/<id>-<slug>: the slug varies by referrer
        # while the numeric id is the identity. Production dup pair:
        # newyorklife /careers/job/39995361-senior-... vs .../39995361.
        assert (
            normalize_job_url(
                "https://careers.newyorklife.com/careers/job/39995361-senior-associate-model-validation-and"
            )
            == "https://careers.newyorklife.com/careers/job/39995361"
        )
        assert (
            normalize_job_url(
                "https://morganstanley.eightfold.ai/careers/job/549795932448-market-risk-analytics-associate"
            )
            == "https://morganstanley.eightfold.ai/careers/job/549795932448"
        )

    def test_slug_strip_scoped_to_careers_job_shape(self):
        # Anything not exactly /careers/job/<6+ digit id>-<slug> is untouched:
        # a short numeric prefix, a different path root, or extra path segments
        # might be load-bearing on an unknown site.
        for url in (
            "https://co.com/careers/job/123-team-lead",  # id too short
            "https://co.com/jobs/549795932448-market-risk",  # not /careers/job/
            "https://co.com/careers/job/549795932448-market/extra",  # extra segment
            "https://careers.smbcgroup.com/smbc/job/Jersey-City-Associate-NJ-07311/1412538800/",
        ):
            assert normalize_job_url(url) == url


class TestNonHttpPassthrough:
    def test_non_http_returned_unchanged(self):
        assert normalize_job_url("mailto:x@y.com") == "mailto:x@y.com"

    def test_empty_string(self):
        assert normalize_job_url("") == ""

    def test_whitespace_trimmed(self):
        assert normalize_job_url("  https://co.com/job/1  ") == "https://co.com/job/1"
