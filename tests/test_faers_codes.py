"""Unit tests for the faers_codes translation module.

These are pure function tests - no HTTP, no async, no mocking needed.
They validate that ICH E2B code -> human-readable label mappings return
the right value for all documented codes plus reasonable behavior for
None, empty strings, and unknown codes.
"""

from __future__ import annotations

import pytest

from mcp_server_openfda.faers_codes import (
    DRUG_CHARACTERIZATION,
    PATIENT_AGE_UNIT,
    PATIENT_SEX,
    REACTION_OUTCOME,
    REPORTER_QUALIFICATION,
    format_faers_date,
    normalize_meddra_term,
    translate,
    translate_serious,
)


# ---------------------------------------------------------------------------
# translate() helper
# ---------------------------------------------------------------------------

class TestTranslate:
    def test_returns_label_for_known_code(self):
        assert translate(PATIENT_SEX, "1") == "Male"
        assert translate(PATIENT_SEX, "2") == "Female"
        assert translate(PATIENT_SEX, "0") == "Unknown"

    def test_accepts_int_code(self):
        # FAERS sometimes ships codes as ints, sometimes as strings.
        assert translate(PATIENT_SEX, 1) == "Male"
        assert translate(REACTION_OUTCOME, 5) == "Fatal"

    def test_returns_none_for_missing_input(self):
        assert translate(PATIENT_SEX, None) is None
        assert translate(PATIENT_SEX, "") is None

    def test_returns_none_for_unknown_code(self):
        assert translate(PATIENT_SEX, "99") is None
        assert translate(DRUG_CHARACTERIZATION, "unknown") is None


# ---------------------------------------------------------------------------
# Full code table coverage
# ---------------------------------------------------------------------------

class TestPatientSex:
    @pytest.mark.parametrize(
        "code, expected",
        [("0", "Unknown"), ("1", "Male"), ("2", "Female")],
    )
    def test_all_documented_codes(self, code, expected):
        assert translate(PATIENT_SEX, code) == expected


class TestReactionOutcome:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("1", "Recovered/resolved"),
            ("2", "Recovering/resolving"),
            ("3", "Not recovered/not resolved"),
            ("4", "Recovered/resolved with sequelae"),
            ("5", "Fatal"),
            ("6", "Unknown"),
        ],
    )
    def test_all_documented_codes(self, code, expected):
        assert translate(REACTION_OUTCOME, code) == expected


class TestDrugCharacterization:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("1", "Suspect"),
            ("2", "Concomitant"),
            ("3", "Interacting"),
            ("4", "Drug not administered"),
        ],
    )
    def test_all_documented_codes(self, code, expected):
        assert translate(DRUG_CHARACTERIZATION, code) == expected


class TestReporterQualification:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("1", "Physician"),
            ("2", "Pharmacist"),
            ("3", "Other health professional"),
            ("4", "Lawyer"),
            ("5", "Consumer or non-health professional"),
        ],
    )
    def test_all_documented_codes(self, code, expected):
        assert translate(REPORTER_QUALIFICATION, code) == expected


class TestPatientAgeUnit:
    @pytest.mark.parametrize(
        "code, expected",
        [
            ("800", "Decade"),
            ("801", "Year"),
            ("802", "Month"),
            ("803", "Week"),
            ("804", "Day"),
            ("805", "Hour"),
        ],
    )
    def test_all_documented_codes(self, code, expected):
        assert translate(PATIENT_AGE_UNIT, code) == expected


# ---------------------------------------------------------------------------
# translate_serious
# ---------------------------------------------------------------------------

class TestTranslateSerious:
    def test_serious_code_1_is_true(self):
        assert translate_serious("1") is True
        assert translate_serious(1) is True

    def test_serious_code_2_is_false(self):
        assert translate_serious("2") is False
        assert translate_serious(2) is False

    def test_missing_or_unknown_is_none(self):
        assert translate_serious(None) is None
        assert translate_serious("") is None
        assert translate_serious("99") is None


# ---------------------------------------------------------------------------
# format_faers_date
# ---------------------------------------------------------------------------

class TestFormatFaersDate:
    def test_valid_yyyymmdd_converts_to_iso(self):
        assert format_faers_date("20210507") == "2021-05-07"
        assert format_faers_date("20260101") == "2026-01-01"

    def test_accepts_int_input(self):
        assert format_faers_date(20210507) == "2021-05-07"

    def test_none_and_empty_return_none(self):
        assert format_faers_date(None) is None
        assert format_faers_date("") is None

    def test_malformed_input_passes_through(self):
        # A PV reviewer should see raw data if it's malformed, not None.
        assert format_faers_date("2021") == "2021"
        assert format_faers_date("not-a-date") == "not-a-date"


# ---------------------------------------------------------------------------
# normalize_meddra_term
# ---------------------------------------------------------------------------

class TestNormalizeMeddraTerm:
    def test_uppercase_becomes_sentence_case(self):
        assert normalize_meddra_term("DIARRHOEA") == "Diarrhoea"
        assert (
            normalize_meddra_term("MALIGNANT NEOPLASM PROGRESSION")
            == "Malignant neoplasm progression"
        )

    def test_already_sentence_case_stays_sentence_case(self):
        assert normalize_meddra_term("Diarrhoea") == "Diarrhoea"

    def test_none_and_empty_return_none(self):
        assert normalize_meddra_term(None) is None
        assert normalize_meddra_term("") is None
