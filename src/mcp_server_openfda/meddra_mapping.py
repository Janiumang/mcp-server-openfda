"""MedDRA lay-term to Preferred Term (PT) mapping.

Purpose
-------
openFDA stores adverse-reaction terms as MedDRA Preferred Terms in
`patient.reaction.reactionmeddrapt` - values like "Headache", "Pneumonitis",
"Myocardial infarction". LLMs and end users routinely pass lay terms
("headache", "chest pain", "shortness of breath") through the reaction
filter, which then silently under-matches because FAERS does not store
those strings verbatim.

This module holds a curated dictionary of common lay terms mapped to
their canonical MedDRA PT sets. Callers use `expand_reaction_term()` to
turn one lay input into a list of PTs that get OR-joined at the query
layer, dramatically improving recall on non-PV-fluent inputs.

Licensing note
--------------
The MedDRA terminology itself is under MSSO license and is not
redistributed here. What this module contains is a WORD-LEVEL ASSOCIATION
dictionary - it maps English lay terms to specific PT strings, similar
to a domain thesaurus. It does NOT ship MedDRA hierarchies (SOC, HLGT,
HLT, LLT), MedDRA codes, or the terminology structure. Using this
module does not require a MedDRA license.

Limitations
-----------
    - This is a starter dictionary of ~40 common terms. Extend by
      adding entries to LAY_TO_MEDDRA_PT below.
    - Mappings are approximate. MedDRA has strict hierarchies; a lay
      term like "rash" can associate with dozens of PTs across the
      "Rashes and eruptions" HLT. We pick the most common 3-5 to balance
      recall with precision, based on typical FAERS reporting patterns.
    - If a term's lowercase form is not in the dictionary, we pass it
      through unchanged, assuming it is either already a MedDRA PT or a
      term the caller wants matched verbatim.

Future work
-----------
For proper MedDRA integration (SMQs, LLT-to-PT lookup, hierarchy walks),
a v0.3+ feature would integrate an MSSO-licensed dictionary file or
API, ideally behind a configuration flag so open-source callers can
still use the lay dictionary while licensed users get full MedDRA.
"""

from __future__ import annotations

from typing import Any

# Curated lay-term -> MedDRA PT mapping.
#
# Keys are always the lowercase form of a lay term. Values are lists of
# MedDRA PTs in canonical sentence case (as they appear in
# reactionmeddrapt). Order within each list is roughly by expected
# reporting frequency, most common first.
LAY_TO_MEDDRA_PT: dict[str, list[str]] = {
    # -- Neurological / pain --
    "headache": ["Headache", "Migraine", "Tension headache"],
    "dizziness": ["Dizziness", "Vertigo", "Presyncope"],
    "seizure": ["Seizure", "Convulsion"],
    "seizures": ["Seizure", "Convulsion"],
    "confusion": ["Confusional state", "Disorientation"],
    "chest pain": ["Chest pain", "Chest discomfort", "Angina pectoris"],
    "abdominal pain": [
        "Abdominal pain", "Abdominal pain upper", "Abdominal pain lower"
    ],
    "stomach pain": [
        "Abdominal pain", "Abdominal pain upper", "Abdominal pain lower"
    ],
    "back pain": ["Back pain", "Musculoskeletal pain"],

    # -- Gastrointestinal --
    "nausea": ["Nausea", "Vomiting"],
    "vomit": ["Vomiting"],
    "vomiting": ["Vomiting"],
    "diarrhea": ["Diarrhoea"],
    "diarrhoea": ["Diarrhoea"],
    "constipation": ["Constipation"],

    # -- Dermatology --
    "rash": [
        "Rash", "Rash erythematous", "Rash maculo-papular", "Pruritus", "Erythema"
    ],
    "itching": ["Pruritus"],
    "hives": ["Urticaria"],
    "swelling": ["Oedema", "Oedema peripheral", "Swelling"],
    "hair loss": ["Alopecia"],

    # -- Cardiovascular / vascular --
    "high blood pressure": ["Hypertension", "Blood pressure increased"],
    "low blood pressure": ["Hypotension", "Blood pressure decreased"],
    "heart attack": ["Myocardial infarction", "Acute myocardial infarction"],
    "stroke": [
        "Cerebrovascular accident", "Ischaemic stroke", "Haemorrhagic stroke"
    ],
    "blood clot": [
        "Deep vein thrombosis", "Pulmonary embolism", "Thrombosis"
    ],

    # -- Respiratory --
    "shortness of breath": ["Dyspnoea"],
    "sob": ["Dyspnoea"],
    "cough": ["Cough"],
    "pneumonia": ["Pneumonia"],
    "pneumonitis": ["Pneumonitis", "Interstitial lung disease"],

    # -- Constitutional --
    "fatigue": ["Fatigue", "Asthenia", "Malaise"],
    "tiredness": ["Fatigue", "Asthenia"],
    "fever": ["Pyrexia", "Body temperature increased"],
    "weight loss": ["Weight decreased"],
    "weight gain": ["Weight increased"],
    "insomnia": ["Insomnia", "Sleep disorder"],

    # -- Renal / hepatic --
    "kidney failure": ["Renal failure", "Acute kidney injury"],
    "liver problems": ["Hepatic function abnormal", "Hepatitis"],
    "hepatitis": [
        "Hepatitis", "Autoimmune hepatitis", "Immune-mediated hepatitis"
    ],
    "colitis": ["Colitis", "Immune-mediated colitis"],

    # -- Allergy / immune --
    "allergic reaction": [
        "Hypersensitivity", "Anaphylactic reaction", "Angioedema"
    ],
    "anaphylaxis": ["Anaphylactic reaction", "Anaphylactic shock"],

    # -- Mental health --
    "anxiety": ["Anxiety", "Nervousness"],
    "depression": ["Depression", "Depressed mood"],

    # -- Infection --
    "uti": ["Urinary tract infection"],
    "urinary tract infection": ["Urinary tract infection"],
}


def expand_reaction_term(term: str | None) -> list[str]:
    """Expand a possibly-lay reaction term into a list of MedDRA PTs.

    If the lowercase form of `term` is a known lay term in
    LAY_TO_MEDDRA_PT, return the mapped list of PTs. Otherwise pass
    the input through unchanged as a single-item list so callers can
    uniformly build query clauses.

    Empty, None, or whitespace-only inputs return an empty list; the
    caller should skip the reaction clause entirely in that case.
    """
    if not term or not term.strip():
        return []
    key = term.strip().lower()
    if key in LAY_TO_MEDDRA_PT:
        return list(LAY_TO_MEDDRA_PT[key])
    return [term]


def describe_expansion(term: str | None) -> dict[str, Any] | None:
    """Return metadata describing a lay-term expansion, or None.

    Callers use this to surface transparency in tool responses: when a
    query was broadened from "headache" to three MedDRA PTs, the LLM
    (and human reader) should see that happened rather than guess.

    Returns None when:
        - term is empty or None
        - term was passed through unchanged (already a MedDRA PT or
          an unknown term the caller wanted matched verbatim)

    Returns a metadata dict when the term was expanded:
        {
            "original_term": <what the caller passed>,
            "recognized_as_lay_term": True,
            "expanded_to_meddra_pts": [<PT>, ...],
            "note": <human-readable explanation>
        }
    """
    if not term:
        return None
    key = term.strip().lower()
    if key not in LAY_TO_MEDDRA_PT:
        return None
    pts = list(LAY_TO_MEDDRA_PT[key])
    return {
        "original_term": term,
        "recognized_as_lay_term": True,
        "expanded_to_meddra_pts": pts,
        "note": (
            f"Query broadened from '{term}' to {len(pts)} MedDRA Preferred "
            f"Term(s): {', '.join(pts)}. To skip expansion, pass a term "
            "that is not in the lay-term dictionary (typically a canonical "
            "MedDRA PT itself)."
        ),
    }


def known_lay_terms() -> list[str]:
    """Return a sorted list of lay terms this module recognizes.

    Useful for introspection tools or docs that want to enumerate what
    the mapping covers.
    """
    return sorted(LAY_TO_MEDDRA_PT.keys())
