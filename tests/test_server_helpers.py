"""Tests for the pure functions in server.py.

Everything here is synchronous unit testing - no HTTP, no async. Covers:
    - Query-string builders for /drug/event, /drug/label, /drug/enforcement.
    - Record tidiers (_tidy_record, _tidy_recall) that apply code
      translations and pick PV-relevant field subsets.
    - Section helpers for the label tool (_section_text, _truncate_section).
    - Pivot-count labeling for the aggregate tool (_label_pivot_count).
"""

from __future__ import annotations

import pytest

from mcp_server_openfda.server import (
    VALID_PIVOTS,
    _RECALL_CLASS_DESCRIPTIONS,
    _build_adverse_event_search,
    _build_label_search,
    _build_recall_search,
    _date_to_openfda,
    _label_pivot_count,
    _section_text,
    _tidy_recall,
    _tidy_record,
    _truncate_section,
    _VALID_RECALL_CLASSIFICATIONS,
    _VALID_RECALL_STATUSES,
)


# ---------------------------------------------------------------------------
# Date conversion
# ---------------------------------------------------------------------------

class TestDateToOpenFDA:
    def test_iso_date_becomes_yyyymmdd(self):
        assert _date_to_openfda("2021-05-07") == "20210507"

    def test_already_yyyymmdd_passes_through(self):
        # Removing "-" is idempotent for a date with no dashes.
        assert _date_to_openfda("20210507") == "20210507"


# ---------------------------------------------------------------------------
# Adverse-event search query builder
# ---------------------------------------------------------------------------

class TestBuildAdverseEventSearch:
    def test_drug_name_only_includes_three_fields(self):
        q = _build_adverse_event_search(
            drug_name="pembrolizumab",
            reaction=None,
            start_date=None,
            end_date=None,
            min_age=None,
            max_age=None,
            country=None,
        )
        assert 'patient.drug.openfda.generic_name:"pembrolizumab"' in q
        assert 'patient.drug.openfda.brand_name:"pembrolizumab"' in q
        assert 'patient.drug.openfda.substance_name:"pembrolizumab"' in q
        assert " OR " in q

    def test_reaction_adds_meddra_clause(self):
        q = _build_adverse_event_search(
            drug_name="pembrolizumab",
            reaction="Pneumonitis",
            start_date=None,
            end_date=None,
            min_age=None,
            max_age=None,
            country=None,
        )
        assert 'patient.reaction.reactionmeddrapt:"Pneumonitis"' in q

    def test_date_range_uses_yyyymmdd(self):
        q = _build_adverse_event_search(
            drug_name="pembrolizumab",
            reaction=None,
            start_date="2021-05-07",
            end_date="2026-05-07",
            min_age=None,
            max_age=None,
            country=None,
        )
        assert "receivedate:[20210507 TO 20260507]" in q

    def test_only_start_date_uses_wide_upper(self):
        q = _build_adverse_event_search(
            drug_name="x",
            reaction=None,
            start_date="2021-01-01",
            end_date=None,
            min_age=None,
            max_age=None,
            country=None,
        )
        assert "receivedate:[20210101 TO 21000101]" in q

    def test_age_range(self):
        q = _build_adverse_event_search(
            drug_name="x",
            reaction=None,
            start_date=None,
            end_date=None,
            min_age=65,
            max_age=90,
            country=None,
        )
        assert "patient.patientonsetage:[65 TO 90]" in q

    def test_only_min_age(self):
        q = _build_adverse_event_search(
            drug_name="x",
            reaction=None,
            start_date=None,
            end_date=None,
            min_age=65,
            max_age=None,
            country=None,
        )
        assert "patient.patientonsetage:[65 TO 999]" in q

    def test_country_added(self):
        q = _build_adverse_event_search(
            drug_name="x",
            reaction=None,
            start_date=None,
            end_date=None,
            min_age=None,
            max_age=None,
            country="US",
        )
        assert "primarysource.reportercountry:US" in q

    def test_all_filters_joined_with_and(self):
        q = _build_adverse_event_search(
            drug_name="pembrolizumab",
            reaction="Diarrhoea",
            start_date="2020-01-01",
            end_date="2025-12-31",
            min_age=65,
            max_age=None,
            country="US",
        )
        # Every optional clause should be present, all joined by AND.
        assert q.count(" AND ") == 4  # 5 clauses -> 4 joins

    def test_lay_term_reaction_expands_to_or_clause(self):
        """'headache' should expand to multiple MedDRA PTs joined with OR."""
        q = _build_adverse_event_search(
            drug_name="x",
            reaction="headache",
            start_date=None,
            end_date=None,
            min_age=None,
            max_age=None,
            country=None,
        )
        # Should contain a parenthesized OR clause with the mapped PTs.
        assert 'patient.reaction.reactionmeddrapt:"Headache"' in q
        assert 'patient.reaction.reactionmeddrapt:"Migraine"' in q
        assert " OR " in q
        # And it should be wrapped in parens so it interacts with outer AND.
        assert "(patient.reaction.reactionmeddrapt:" in q

    def test_meddra_pt_reaction_passes_through_as_single_clause(self):
        """A term not in the lay dictionary stays as a single exact-match clause."""
        # "Cardiac tamponade" is a real MedDRA PT that is not in our
        # lay-term dictionary, so it must pass through unchanged.
        q = _build_adverse_event_search(
            drug_name="x",
            reaction="Cardiac tamponade",
            start_date=None,
            end_date=None,
            min_age=None,
            max_age=None,
            country=None,
        )
        assert 'patient.reaction.reactionmeddrapt:"Cardiac tamponade"' in q
        # No OR clause for single-PT match.
        assert "OR patient.reaction" not in q


# ---------------------------------------------------------------------------
# _tidy_record: FAERS record -> PV-friendly subset with translations
# ---------------------------------------------------------------------------

class TestTidyRecord:
    def test_translates_codes(self, fixture_loader):
        raw = fixture_loader("drug_event_pembrolizumab_search")["results"][0]
        tidied = _tidy_record(raw)
        assert tidied["patient_sex"] == "Female"
        assert tidied["reporter_qualification"] == "Consumer or non-health professional"
        assert tidied["patient_age_unit"] == "Year"
        assert tidied["serious"] is True
        assert tidied["received_date"] == "2021-05-07"

    def test_translates_drug_characterization(self, fixture_loader):
        raw = fixture_loader("drug_event_pembrolizumab_search")["results"][0]
        tidied = _tidy_record(raw)
        # Record 1: KEYTRUDA characterization "2" -> Concomitant, LENVIMA "1" -> Suspect.
        chars = [d["characterization"] for d in tidied["drugs"]]
        assert "Concomitant" in chars
        assert "Suspect" in chars

    def test_translates_reaction_outcomes(self, fixture_loader):
        raw = fixture_loader("drug_event_pembrolizumab_search")["results"][0]
        tidied = _tidy_record(raw)
        outcomes = [r["outcome"] for r in tidied["reactions"]]
        assert "Recovering/resolving" in outcomes  # code "2"
        assert "Unknown" in outcomes  # code "6"

    def test_patient_age_coerced_to_int(self, fixture_loader):
        raw = fixture_loader("drug_event_pembrolizumab_search")["results"][0]
        tidied = _tidy_record(raw)
        assert tidied["patient_age"] == 67  # int, not "67"

    def test_patient_died_from_second_record(self, fixture_loader):
        # Record 2 has patientdeath key present.
        raw = fixture_loader("drug_event_pembrolizumab_search")["results"][1]
        tidied = _tidy_record(raw)
        assert tidied["patient_died"] is True

    def test_patient_died_false_when_no_key(self, fixture_loader):
        # Record 1 has no patientdeath key.
        raw = fixture_loader("drug_event_pembrolizumab_search")["results"][0]
        tidied = _tidy_record(raw)
        assert tidied["patient_died"] is False


# ---------------------------------------------------------------------------
# _label_pivot_count
# ---------------------------------------------------------------------------

class TestLabelPivotCount:
    def test_reaction_normalizes_to_sentence_case(self):
        result = _label_pivot_count(
            "reaction", {"term": "DIARRHOEA", "count": 1613}
        )
        assert result == {"label": "Diarrhoea", "count": 1613}

    def test_country_passes_through(self):
        result = _label_pivot_count("country", {"term": "US", "count": 31839})
        assert result == {"label": "US", "count": 31839}

    def test_year_passes_through(self):
        result = _label_pivot_count("year", {"term": "2024", "count": 16080})
        assert result == {"label": "2024", "count": 16080}

    def test_reporter_qualification_translates_code(self):
        result = _label_pivot_count(
            "reporter_qualification", {"term": "1", "count": 49081}
        )
        assert result == {"label": "Physician", "count": 49081}

    def test_reporter_qualification_unknown_code_surfaced(self):
        result = _label_pivot_count(
            "reporter_qualification", {"term": "99", "count": 5}
        )
        assert result["label"] == "Code 99"

    def test_concomitant_drug_title_cases(self):
        result = _label_pivot_count(
            "concomitant_drug", {"term": "CARBOPLATIN", "count": 19732}
        )
        assert result == {"label": "Carboplatin", "count": 19732}


# ---------------------------------------------------------------------------
# _build_label_search
# ---------------------------------------------------------------------------

class TestBuildLabelSearch:
    def test_top_level_openfda_fields(self):
        # In /drug/label the openfda block is at top level (NOT under patient.drug).
        q = _build_label_search("pembrolizumab")
        assert 'openfda.generic_name:"pembrolizumab"' in q
        assert 'openfda.brand_name:"pembrolizumab"' in q
        assert 'openfda.substance_name:"pembrolizumab"' in q
        # And it should NOT include patient.drug. prefix.
        assert "patient.drug.openfda" not in q

    def test_no_manufacturer_omits_manufacturer_clause(self):
        q = _build_label_search("pembrolizumab")
        assert "manufacturer_name" not in q

    def test_manufacturer_adds_phrase_match_and_clause(self):
        q = _build_label_search("pembrolizumab", manufacturer="Merck Sharp & Dohme LLC")
        # AND joins the name clause with the manufacturer phrase-match.
        assert 'openfda.manufacturer_name:"Merck Sharp & Dohme LLC"' in q
        assert " AND " in q

    def test_manufacturer_strips_whitespace(self):
        q = _build_label_search(
            "pembrolizumab", manufacturer="  Merck Sharp & Dohme LLC  "
        )
        assert 'openfda.manufacturer_name:"Merck Sharp & Dohme LLC"' in q


# ---------------------------------------------------------------------------
# _section_text: list-of-strings -> joined string / None
# ---------------------------------------------------------------------------

class TestSectionText:
    def test_list_joined_with_double_newline(self):
        assert _section_text(["Part 1.", "Part 2."]) == "Part 1.\n\nPart 2."

    def test_list_with_empty_and_whitespace_filtered(self):
        assert _section_text(["Part 1.", "", "   ", "Part 2."]) == "Part 1.\n\nPart 2."

    def test_empty_list_returns_none(self):
        assert _section_text([]) is None

    def test_none_returns_none(self):
        assert _section_text(None) is None

    def test_string_stripped(self):
        assert _section_text("  hello  ") == "hello"

    def test_empty_string_returns_none(self):
        assert _section_text("") is None
        assert _section_text("   ") is None


# ---------------------------------------------------------------------------
# _truncate_section: cap length with inline recovery note
# ---------------------------------------------------------------------------

class TestTruncateSection:
    def test_short_section_passes_through(self):
        text = "Short section content."
        assert _truncate_section(text, limit=1000, section_name="x") == text

    def test_long_section_truncated_with_note(self):
        text = "A" * 5000
        result = _truncate_section(text, limit=1000, section_name="adverse_reactions")
        assert result.startswith("A" * 1000)
        assert "Section truncated" in result
        assert "sections=['adverse_reactions']" in result
        assert "5,000 characters" in result

    def test_none_returns_none(self):
        assert _truncate_section(None, limit=1000, section_name="x") is None


# ---------------------------------------------------------------------------
# Recall search + tidy
# ---------------------------------------------------------------------------

class TestBuildRecallSearch:
    def test_drug_name_only(self):
        q = _build_recall_search(
            drug_name="metformin",
            firm=None,
            classification=None,
            status=None,
            start_date=None,
            end_date=None,
        )
        assert 'openfda.generic_name:"metformin"' in q
        assert "recalling_firm" not in q

    def test_firm_only_single_word_tokenized(self):
        q = _build_recall_search(
            drug_name=None,
            firm="Pfizer",
            classification=None,
            status=None,
            start_date=None,
            end_date=None,
        )
        # Single-word firm gets tokenized match (unquoted).
        assert "recalling_firm:Pfizer" in q
        assert '"Pfizer"' not in q  # no phrase match here

    def test_firm_multi_word_phrase_matched(self):
        q = _build_recall_search(
            drug_name=None,
            firm="Pfizer Inc",
            classification=None,
            status=None,
            start_date=None,
            end_date=None,
        )
        assert 'recalling_firm:"Pfizer Inc"' in q

    def test_classification_and_status(self):
        q = _build_recall_search(
            drug_name="metformin",
            firm=None,
            classification="Class II",
            status="Ongoing",
            start_date=None,
            end_date=None,
        )
        assert 'classification:"Class II"' in q
        assert 'status:"Ongoing"' in q

    def test_date_range_on_recall_initiation_date(self):
        q = _build_recall_search(
            drug_name="metformin",
            firm=None,
            classification=None,
            status=None,
            start_date="2024-01-01",
            end_date="2025-12-31",
        )
        assert "recall_initiation_date:[20240101 TO 20251231]" in q


class TestTidyRecall:
    def test_tidies_and_adds_class_description(self, fixture_loader):
        raw = fixture_loader("drug_enforcement_pfizer")["results"][0]
        tidied = _tidy_recall(raw)

        assert tidied["recall_number"] == "D-0590-2025"
        assert tidied["classification"] == "Class II"
        assert (
            tidied["class_description"]
            == _RECALL_CLASS_DESCRIPTIONS["Class II"]
        )
        # Dates ISO-formatted
        assert tidied["recall_initiation_date"] == "2025-08-04"
        assert tidied["termination_date"] is None


# ---------------------------------------------------------------------------
# Constants smoke tests
# ---------------------------------------------------------------------------

class TestConstants:
    def test_valid_pivots_has_six_entries(self):
        assert len(VALID_PIVOTS) == 6

    def test_valid_pivots_contains_expected_names(self):
        expected = {
            "reaction",
            "country",
            "year",
            "reporter_qualification",
            "concomitant_drug",
            "seriousness_subtype",
        }
        assert set(VALID_PIVOTS) == expected

    def test_recall_classifications(self):
        assert _VALID_RECALL_CLASSIFICATIONS == ("Class I", "Class II", "Class III")

    def test_recall_statuses(self):
        assert set(_VALID_RECALL_STATUSES) == {
            "Ongoing", "Terminated", "Completed", "Pending"
        }
