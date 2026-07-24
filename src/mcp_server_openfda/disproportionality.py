"""Disproportionality analysis for pharmacovigilance signal detection.

This module implements the Reporting Odds Ratio (ROR), a foundational
statistic used in PV to detect drug-adverse-reaction associations that
appear more frequently in spontaneous-reporting databases (like FAERS)
than would be expected given base rates.

The math is standard 2x2 contingency-table analysis:

                       | Reaction R present | Reaction R absent | totals
    ------------------+--------------------+-------------------+---------
    Drug D reports    |        a           |        b          |  N_ax
    Other drug reports|        c           |        d          |  N_bx
    ------------------+--------------------+-------------------+---------
    totals            |       N_xr         |       N_bx        |  N

    ROR = (a * d) / (b * c)
        = odds(reaction | drug D) / odds(reaction | other drugs)

Signal criteria commonly used in PV literature:
    - ROR > 1.0 (positive association)
    - 95% CI lower bound > 1.0 (statistically distinguishable from 1)
    - a >= 3 (minimum observed cases for stability)

References
----------
- Rothman KJ, Lanes S, Sacks ST. The reporting odds ratio and its
  advantages over the proportional reporting ratio.
- van Puijenbroek EP, et al. A comparison of measures of
  disproportionality for signal detection in spontaneous reporting
  systems for adverse drug reactions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# Standard signal threshold: at least 3 co-reports for stability.
MIN_CASES_FOR_SIGNAL = 3
# 95% CI multiplier for a normal-approximation.
Z_95 = 1.96


@dataclass
class RORResult:
    """Result of a Reporting Odds Ratio computation.

    Attributes:
        a, b, c, d: The four cells of the contingency table.
            a = drug D reports with reaction R
            b = drug D reports without reaction R
            c = other-drug reports with reaction R
            d = other-drug reports without reaction R
        ror: Reporting Odds Ratio, or None if degenerate.
        ci_95_lower: Lower bound of the 95% confidence interval.
        ci_95_upper: Upper bound of the 95% confidence interval.
        signal: True when standard PV signal criteria are met, False
            when they are not, None when the calculation was degenerate.
        notes: Human-readable caveats (small n, degenerate cell, etc.).
    """

    a: int
    b: int
    c: int
    d: int
    ror: float | None
    ci_95_lower: float | None
    ci_95_upper: float | None
    signal: bool | None
    notes: list[str]


def calculate_ror(
    reports_with_drug_and_reaction: int,
    reports_with_drug_total: int,
    reports_with_reaction_total: int,
    reports_total: int,
) -> RORResult:
    """Compute ROR + 95% CI + signal flag from FAERS totals.

    Args:
        reports_with_drug_and_reaction: `a` cell - count of FAERS reports
            containing BOTH the target drug and the target reaction.
        reports_with_drug_total: Sum of the drug's row (a + b) - count of
            all reports containing the target drug.
        reports_with_reaction_total: Sum of the reaction's column (a + c) -
            count of all reports containing the target reaction, from any
            drug.
        reports_total: Grand total (a + b + c + d) - count of all reports
            in the sampling frame (respecting whatever date/age/country
            filters the caller applied consistently to all four queries).

    Returns:
        RORResult with the ratio, confidence interval, signal flag, and
        any interpretive notes.
    """
    a = reports_with_drug_and_reaction
    n_ax = reports_with_drug_total
    n_xr = reports_with_reaction_total
    n = reports_total

    b = max(0, n_ax - a)
    c = max(0, n_xr - a)
    d = max(0, n - a - b - c)

    notes: list[str] = []

    # a == 0: no co-reports observed. ROR is 0 mathematically but the
    # interpretation is "no signal" - return that plainly.
    if a == 0:
        notes.append(
            "No reports contain both the drug and the reaction; ROR = 0. "
            "No disproportionality signal."
        )
        return RORResult(
            a=a, b=b, c=c, d=d,
            ror=0.0,
            ci_95_lower=None,
            ci_95_upper=None,
            signal=False,
            notes=notes,
        )

    # Degenerate: one of b, c, d is zero. ROR is undefined (division by
    # zero) or CI is undefined (1/0 in the SE formula). Surface honestly.
    if b == 0 or c == 0 or d == 0:
        notes.append(
            "Contingency table has a zero cell (b, c, or d = 0). "
            "ROR is mathematically undefined here - one of the odds "
            "denominators is zero. Interpret co-report count `a` directly."
        )
        return RORResult(
            a=a, b=b, c=c, d=d,
            ror=None,
            ci_95_lower=None,
            ci_95_upper=None,
            signal=None,
            notes=notes,
        )

    # Standard ROR + 95% CI on the log scale, exponentiated back.
    ror = (a * d) / (b * c)
    ln_ror = math.log(ror)
    se = math.sqrt(1 / a + 1 / b + 1 / c + 1 / d)
    ci_lower = math.exp(ln_ror - Z_95 * se)
    ci_upper = math.exp(ln_ror + Z_95 * se)

    # Small-n caveat: PV convention is to flag <3 co-reports as unstable.
    if a < MIN_CASES_FOR_SIGNAL:
        notes.append(
            f"Only {a} co-report(s) observed - below the {MIN_CASES_FOR_SIGNAL}-case "
            "convention for stable signal detection. Interpret with caution."
        )

    signal = (
        ror > 1.0
        and ci_lower > 1.0
        and a >= MIN_CASES_FOR_SIGNAL
    )

    return RORResult(
        a=a, b=b, c=c, d=d,
        ror=ror,
        ci_95_lower=ci_lower,
        ci_95_upper=ci_upper,
        signal=signal,
        notes=notes,
    )
