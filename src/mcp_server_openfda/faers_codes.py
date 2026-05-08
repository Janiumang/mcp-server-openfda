"""FAERS code translations.

FAERS records reference adverse-event report attributes (patient sex,
drug characterization, reaction outcome, etc.) as ICH E2B coded values.
Returning those codes raw is valid but unhelpful for non-PV readers and
for LLMs reading our tool output. This module is the single source of
truth for translating those codes into human-readable labels.

References used to build these tables:
    - ICH E2B(R3) Step 5 Implementation Guide (data element definitions)
    - FDA FAERS Quarterly Data Files documentation
    - openFDA /drug/event searchable fields:
      https://open.fda.gov/apis/drug/event/searchable-fields/

Conventions:
    - Lookups return None for missing or unknown codes; we never
      fabricate a label. Missing data is meaningful in PV.
    - Boolean translations (e.g. seriousness flag) collapse '1'/'2' to
      True/False. Other values become None.
    - Term-case normalization for MedDRA PTs uses .capitalize() — close
      to MedDRA sentence-case standard. Imperfect for terms with proper
      nouns ("Stevens-Johnson syndrome") but acceptable for v0.1.
      Tracked for v0.2 in OPEN_ISSUES.md.
"""

from __future__ import annotations

# patient.patientsex - ICH E2B element B.1.5
PATIENT_SEX: dict[str, str] = {
    "0": "Unknown",
    "1": "Male",
    "2": "Female",
}

# patient.reaction.reactionoutcome - ICH E2B element B.2.i.4
REACTION_OUTCOME: dict[str, str] = {
    "1": "Recovered/resolved",
    "2": "Recovering/resolving",
    "3": "Not recovered/not resolved",
    "4": "Recovered/resolved with sequelae",
    "5": "Fatal",
    "6": "Unknown",
}

# patient.drug.drugcharacterization - ICH E2B element B.4.k.1
DRUG_CHARACTERIZATION: dict[str, str] = {
    "1": "Suspect",
    "2": "Concomitant",
    "3": "Interacting",
    "4": "Drug not administered",
}

# primarysource.qualification - ICH E2B element A.2.1.4
REPORTER_QUALIFICATION: dict[str, str] = {
    "1": "Physician",
    "2": "Pharmacist",
    "3": "Other health professional",
    "4": "Lawyer",
    "5": "Consumer or non-health professional",
}

# patient.patientonsetageunit - ICH E2B age unit codes
PATIENT_AGE_UNIT: dict[str, str] = {
    "800": "Decade",
    "801": "Year",
    "802": "Month",
    "803": "Week",
    "804": "Day",
    "805": "Hour",
}


def translate(table: dict[str, str], code: object) -> str | None:
    """Look up a code in a translation table.

    Returns None for missing inputs and unknown codes; we keep the field
    in the response but mark absence rather than fabricating a value.
    Accepts code as anything stringifiable (FAERS occasionally ships
    codes as numeric values, more often as strings).
    """
    if code is None or code == "":
        return None
    return table.get(str(code))


def translate_serious(code: object) -> bool | None:
    """Translate the FAERS `serious` flag to a boolean.

    Returns True for serious, False for non-serious, None when missing
    or unknown. Using bool collapses the FAERS '1'/'2' encoding to its
    PV meaning; missing values stay missing rather than defaulting.
    """
    if code is None or code == "":
        return None
    s = str(code)
    if s == "1":
        return True
    if s == "2":
        return False
    return None


def format_faers_date(yyyymmdd: object) -> str | None:
    """Convert FAERS YYYYMMDD date strings to ISO YYYY-MM-DD.

    FAERS stores dates as compact 8-character strings (sometimes as
    integers, depending on how a record was serialized). ISO format
    is what every downstream consumer expects. Returns the original
    value unchanged if the input doesn't look like a clean YYYYMMDD,
    so a malformed date is still visible to the PV reviewer.
    """
    if yyyymmdd is None or yyyymmdd == "":
        return None
    s = str(yyyymmdd)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def normalize_meddra_term(term: object) -> str | None:
    """Normalize MedDRA PT case toward the canonical sentence-case.

    openFDA's `count=...reactionmeddrapt.exact` queries return terms in
    storage case (often uppercase, e.g. "MALIGNANT NEOPLASM PROGRESSION"),
    while record-level reads return them in MedDRA's native sentence-case
    (e.g. "Diarrhoea"). We normalize the count-query output to match the
    record-level case so the LLM and human reader see a consistent style.

    Imperfect for proper-noun terms ("Stevens-Johnson syndrome" becomes
    "Stevens-johnson syndrome"). Tracked for v0.2 improvement.
    """
    if term is None or term == "":
        return None
    return str(term).capitalize()
