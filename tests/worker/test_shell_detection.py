"""Tests for SPA page-shell detection (is_shell_text).

Threshold calibrated on production data: real JDs measure 0.0-1.8 CSS/JS
tokens per 1000 chars, unrendered shells 30+. These cases sit on both sides.
"""

from packages.infrastructure.jd_fetch.service import is_shell_text


class TestShellDetection:
    def test_css_shell_flagged(self):
        shell = "Company Careers\n\n@font-face {font-family: Arial;} " + (
            ".header {color: rgba(0,0,0,0.5); padding: 10px; margin: 0;} " * 200
        )
        assert is_shell_text(shell)

    def test_js_stub_flagged(self):
        assert is_shell_text("Please enable JavaScript to view this page. Loading...")

    def test_real_jd_not_flagged(self):
        jd = (
            "Senior Market Risk Analyst. Responsibilities include developing VaR "
            "models, stress testing portfolios, and reporting to senior management. "
            "Requirements: 5+ years in market risk, strong Python and SQL. "
        ) * 20
        assert not is_shell_text(jd)

    def test_short_real_text_not_flagged(self):
        assert not is_shell_text("Market Risk Analyst at Goldman Sachs. Apply now on our portal.")

    def test_jd_mentioning_code_not_flagged(self):
        # a real JD that references config/code once stays well under threshold
        jd = (
            "Senior Risk Analyst. The role involves risk modeling, backtesting, and "
            "stakeholder reporting across trading desks. Strong Python skills and "
            "experience with market risk frameworks are required for this position. "
        ) * 30
        jd += " Example config: {'threshold': 0.05}; see the docs for details."
        assert not is_shell_text(jd)

    def test_empty_not_flagged(self):
        assert not is_shell_text("")
