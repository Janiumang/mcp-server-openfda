"""Unit tests for the MedDRA lay-term -> PT mapping module."""

from __future__ import annotations

import pytest

from mcp_server_openfda.meddra_mapping import (
    LAY_TO_MEDDRA_PT,
    describe_expansion,
    expand_reaction_term,
    known_lay_terms,
)


# ---------------------------------------------------------------------------
# expand_reaction_term
# ---------------------------------------------------------------------------

class TestExpandReactionTerm:
    def test_known_lay_term_expands_to_pt_list(self):
        result = expand_reaction_term("headache")
        assert "Headache" in result
        assert len(result) > 1  # dictionary has multiple PTs for headache

    def test_case_insensitive_match(self):
        """Callers may pass 'Headache', 'HEADACHE', or 'headache'."""
        lower = expand_reaction_term("headache")
        upper = expand_reaction_term("HEADACHE")
        mixed = expand_reaction_term("Headache")
        assert lower == upper == mixed

    def test_whitespace_stripped(self):
        assert expand_reaction_term("  headache  ") == expand_reaction_term("headache")

    def test_unknown_term_passes_through(self):
        """A MedDRA PT or unknown term is returned as a single-element list."""
        # "Cardiac tamponade" is a real MedDRA PT that is not in our
        # lay-term dictionary, so it must pass through unchanged.
        assert expand_reaction_term("Cardiac tamponade") == ["Cardiac tamponade"]
        assert expand_reaction_term("Some Unusual Term") == ["Some Unusual Term"]

    def test_none_returns_empty_list(self):
        assert expand_reaction_term(None) == []

    def test_empty_string_returns_empty_list(self):
        assert expand_reaction_term("") == []
        assert expand_reaction_term("   ") == []

    def test_returned_list_is_a_copy(self):
        """Callers should not be able to mutate the module-level dict."""
        result = expand_reaction_term("headache")
        result.append("Mutated")
        assert "Mutated" not in LAY_TO_MEDDRA_PT["headache"]


# ---------------------------------------------------------------------------
# describe_expansion
# ---------------------------------------------------------------------------

class TestDescribeExpansion:
    def test_returns_metadata_for_lay_term(self):
        info = describe_expansion("headache")
        assert info is not None
        assert info["original_term"] == "headache"
        assert info["recognized_as_lay_term"] is True
        assert "Headache" in info["expanded_to_meddra_pts"]
        assert "Migraine" in info["expanded_to_meddra_pts"]
        assert "note" in info

    def test_returns_none_for_pt_pass_through(self):
        """A term not in the dictionary returns None (no expansion happened)."""
        assert describe_expansion("Cardiac tamponade") is None
        assert describe_expansion("Some Rare PT") is None

    def test_returns_none_for_empty_input(self):
        assert describe_expansion("") is None
        assert describe_expansion(None) is None

    def test_note_mentions_the_expansion_size(self):
        info = describe_expansion("rash")
        assert info is not None
        # Note should mention the PT count so the LLM sees "5 PTs" or similar.
        assert str(len(info["expanded_to_meddra_pts"])) in info["note"]


# ---------------------------------------------------------------------------
# known_lay_terms
# ---------------------------------------------------------------------------

class TestKnownLayTerms:
    def test_returns_sorted_list(self):
        terms = known_lay_terms()
        assert terms == sorted(terms)

    def test_contains_expected_lay_terms(self):
        terms = set(known_lay_terms())
        # Spot check a few we know we included.
        assert "headache" in terms
        assert "pneumonitis" in terms
        assert "chest pain" in terms
        assert "kidney failure" in terms


# ---------------------------------------------------------------------------
# Dictionary shape sanity
# ---------------------------------------------------------------------------

class TestMappingShape:
    def test_all_keys_are_lowercase(self):
        for key in LAY_TO_MEDDRA_PT.keys():
            assert key == key.lower(), (
                f"Key {key!r} must be lowercase for case-insensitive lookup."
            )

    def test_all_values_are_non_empty_lists(self):
        for key, pts in LAY_TO_MEDDRA_PT.items():
            assert isinstance(pts, list), f"{key} value must be a list."
            assert len(pts) >= 1, f"{key} value must have at least one PT."

    def test_no_duplicate_pts_within_a_mapping(self):
        for key, pts in LAY_TO_MEDDRA_PT.items():
            assert len(pts) == len(set(pts)), (
                f"Duplicate PTs in mapping for {key!r}: {pts}"
            )

    @pytest.mark.parametrize("lay_term", [
        "headache", "rash", "chest pain", "shortness of breath",
        "pneumonitis", "hepatitis", "colitis", "high blood pressure",
    ])
    def test_common_pv_terms_included(self, lay_term):
        """The dictionary must cover the highest-frequency lay terms."""
        assert lay_term in LAY_TO_MEDDRA_PT
