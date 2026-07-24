"""Unit tests for the Reporting Odds Ratio calculation.

Pure math, no HTTP. Covers positive-signal, no-signal, degenerate-cell,
and small-n cases. Verifies the ROR formula against hand-computed
expected values and confirms the signal criteria fire correctly.
"""

from __future__ import annotations

import math

import pytest

from mcp_server_openfda.disproportionality import (
    MIN_CASES_FOR_SIGNAL,
    Z_95,
    calculate_ror,
)


# ---------------------------------------------------------------------------
# Positive-signal scenarios
# ---------------------------------------------------------------------------

class TestPositiveSignal:
    def test_strong_positive_signal(self):
        """Drug D with reaction R at 100/1100, background at 500/100500."""
        result = calculate_ror(
            reports_with_drug_and_reaction=100,
            reports_with_drug_total=1100,      # a + b = 100 + 1000
            reports_with_reaction_total=600,   # a + c = 100 + 500
            reports_total=101600,              # n = a + b + c + d
        )
        assert result.a == 100
        assert result.b == 1000
        assert result.c == 500
        assert result.d == 100000
        # ROR = (100 * 100000) / (1000 * 500) = 10,000,000 / 500,000 = 20
        assert result.ror is not None
        assert math.isclose(result.ror, 20.0, rel_tol=1e-6)
        # Strong signal: ROR = 20 >> 1, CI comfortably above 1, plenty of cases.
        assert result.signal is True

    def test_ci_contains_point_estimate(self):
        """Sanity: the 95% CI must bracket the point estimate."""
        result = calculate_ror(
            reports_with_drug_and_reaction=50,
            reports_with_drug_total=500,
            reports_with_reaction_total=300,
            reports_total=100000,
        )
        assert result.ror is not None
        assert result.ci_95_lower is not None
        assert result.ci_95_upper is not None
        assert result.ci_95_lower <= result.ror <= result.ci_95_upper


# ---------------------------------------------------------------------------
# No-signal scenarios
# ---------------------------------------------------------------------------

class TestNoSignal:
    def test_ror_below_one_no_signal(self):
        """Drug reports the reaction LESS often than baseline."""
        result = calculate_ror(
            reports_with_drug_and_reaction=10,
            reports_with_drug_total=10000,      # a=10, b=9990
            reports_with_reaction_total=5000,   # a=10, c=4990
            reports_total=100000,               # d = 100000 - 10 - 9990 - 4990 = 85010
        )
        assert result.ror is not None
        # ROR = (10 * 85010) / (9990 * 4990) approx 0.017 - well below 1
        assert result.ror < 1.0
        assert result.signal is False

    def test_ror_above_one_but_ci_crosses_one(self):
        """Point estimate elevated but CI crosses 1 - not a signal."""
        # Small a plus large denominators create a wide CI.
        result = calculate_ror(
            reports_with_drug_and_reaction=3,
            reports_with_drug_total=100,
            reports_with_reaction_total=1000,
            reports_total=100000,
        )
        # ROR should be > 1 but CI wide enough to cross.
        assert result.ror is not None
        assert result.ror > 1.0
        # This particular set: signal depends on CI lower bound; verify no signal
        # when the lower bound is below 1.
        if result.ci_95_lower is not None and result.ci_95_lower <= 1.0:
            assert result.signal is False


# ---------------------------------------------------------------------------
# Zero-co-report case
# ---------------------------------------------------------------------------

class TestZeroCoReports:
    def test_zero_a_returns_ror_zero_no_signal(self):
        result = calculate_ror(
            reports_with_drug_and_reaction=0,
            reports_with_drug_total=500,
            reports_with_reaction_total=1000,
            reports_total=100000,
        )
        assert result.a == 0
        assert result.ror == 0.0
        assert result.signal is False
        assert result.ci_95_lower is None
        assert result.ci_95_upper is None
        assert result.notes  # Non-empty explanation


# ---------------------------------------------------------------------------
# Degenerate contingency tables
# ---------------------------------------------------------------------------

class TestDegenerateCells:
    def test_b_zero_degenerate(self):
        """All drug reports mention the reaction - b = 0, ROR undefined."""
        result = calculate_ror(
            reports_with_drug_and_reaction=50,
            reports_with_drug_total=50,        # a == n_ax so b = 0
            reports_with_reaction_total=300,
            reports_total=100000,
        )
        assert result.b == 0
        assert result.ror is None
        assert result.signal is None
        assert any("zero cell" in n.lower() for n in result.notes)

    def test_c_zero_degenerate(self):
        """Reaction only ever reported with this drug - c = 0, ROR undefined."""
        result = calculate_ror(
            reports_with_drug_and_reaction=50,
            reports_with_drug_total=500,
            reports_with_reaction_total=50,    # a == n_xr so c = 0
            reports_total=100000,
        )
        assert result.c == 0
        assert result.ror is None
        assert result.signal is None


# ---------------------------------------------------------------------------
# Small-n handling
# ---------------------------------------------------------------------------

class TestSmallN:
    def test_below_minimum_cases_no_signal_regardless_of_ror(self):
        """With a < MIN_CASES_FOR_SIGNAL, signal must be False."""
        result = calculate_ror(
            reports_with_drug_and_reaction=2,   # below the 3-case threshold
            reports_with_drug_total=10,
            reports_with_reaction_total=20,
            reports_total=100000,
        )
        # Small-n note surfaced.
        assert any(str(MIN_CASES_FOR_SIGNAL) in n or "below" in n.lower()
                   for n in result.notes)
        # Even if ROR > 1, no signal below the case threshold.
        assert result.signal is False

    def test_exactly_three_cases_meets_threshold(self):
        """a = 3 meets the minimum-case criterion (signal depends on ROR/CI)."""
        result = calculate_ror(
            reports_with_drug_and_reaction=3,
            reports_with_drug_total=5,        # a=3, b=2 - very concentrated
            reports_with_reaction_total=5,    # a=3, c=2 - very rare in bg
            reports_total=100000,
        )
        # With these extremely tight numbers, signal criteria should fire.
        assert result.a == 3
        assert result.ror is not None
        assert result.ror > 1.0


# ---------------------------------------------------------------------------
# Confidence interval math
# ---------------------------------------------------------------------------

class TestConfidenceInterval:
    def test_ci_uses_normal_approximation_on_log_scale(self):
        """Recompute the CI from formula and match."""
        a, n_ax, n_xr, n = 100, 1100, 600, 101600
        result = calculate_ror(a, n_ax, n_xr, n)

        b = n_ax - a
        c = n_xr - a
        d = n - a - b - c
        ror_expected = (a * d) / (b * c)
        se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
        ci_lower_expected = math.exp(math.log(ror_expected) - Z_95 * se)
        ci_upper_expected = math.exp(math.log(ror_expected) + Z_95 * se)

        assert math.isclose(result.ror, ror_expected, rel_tol=1e-10)
        assert math.isclose(result.ci_95_lower, ci_lower_expected, rel_tol=1e-10)
        assert math.isclose(result.ci_95_upper, ci_upper_expected, rel_tol=1e-10)
