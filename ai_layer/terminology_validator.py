"""
Terminology validation against NLM authoritative vocabularies.

RxNorm codes: validated via the free NLM RxNav REST API (no API key required).
SNOMED CT codes: validated via numeric format check (must be a 6-18 digit
numeric string, matching the SNOMED CT concept ID format). Full concept
lookup against the NLM FHIR terminology server requires a UMLS API key —
set UMLS_API_KEY in .env to enable; omit to fall back to format check only.

All validators return:
  True  — code is valid / found in the vocabulary
  False — code is invalid / not found
  None  — API unreachable; pipeline continues without blocking
"""

from __future__ import annotations

import os
from typing import Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ai_layer.models import ConditionRecord, MedicationRecord

_RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
_NLM_FHIR_BASE = "https://cts.nlm.nih.gov/fhir"
_TIMEOUT = 5

_session = requests.Session()
_adapter = HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503]))
_session.mount("https://", _adapter)


def _validate_rxnorm(code: str) -> bool | None:
    """Return True if the RxNorm code resolves to a known concept via RxNav API."""
    try:
        r = _session.get(f"{_RXNORM_BASE}/rxcui/{code}.json", timeout=_TIMEOUT)
        if r.status_code == 200:
            rxcui_list = r.json().get("idGroup", {}).get("rxnormId", [])
            return bool(rxcui_list)
        return False
    except Exception:
        return None


def _validate_snomed(code: str) -> bool | None:
    """
    Validate a SNOMED CT concept ID.

    Format check: must be a 6-18 digit numeric string.
    If UMLS_API_KEY is set, also validates against the NLM FHIR CodeSystem lookup.
    Returns True on format-only pass when UMLS_API_KEY is absent.
    """
    if not code.isdigit() or not (6 <= len(code) <= 18):
        return False

    umls_key = os.environ.get("UMLS_API_KEY")
    if not umls_key:
        return True  # format check passed; full lookup requires UMLS_API_KEY

    try:
        r = _session.get(
            f"{_NLM_FHIR_BASE}/CodeSystem/$lookup",
            params={"system": "http://snomed.info/sct", "code": code},
            headers={"Authorization": f"Bearer {umls_key}"},
            timeout=_TIMEOUT,
        )
        return r.status_code == 200
    except Exception:
        return None


def validate_record(record: Union[ConditionRecord, MedicationRecord]) -> bool | None:
    """Validate the terminology code on a single record."""
    if isinstance(record, ConditionRecord):
        return _validate_snomed(record.condition_code)
    return _validate_rxnorm(record.medication_code)


def validate_batch(
    records: list[Union[ConditionRecord, MedicationRecord]],
) -> dict[tuple[str, str], bool | None]:
    """
    Validate terminology codes for a list of records.

    Returns dict[(patient_id, code)] -> True/False/None.
    None means the API was unreachable; the pipeline continues regardless.
    Logs a summary — does not raise or block on failures.
    """
    results: dict[tuple[str, str], bool | None] = {}
    for r in records:
        code = r.condition_code if isinstance(r, ConditionRecord) else r.medication_code
        results[(r.patient_id, code)] = validate_record(r)
    return results


def log_validation_summary(
    results: dict[tuple[str, str], bool | None],
    print_fn=print,
) -> None:
    """Print a one-line validation summary. Pass context.log.info for Dagster assets."""
    total = len(results)
    valid = sum(1 for v in results.values() if v is True)
    invalid = sum(1 for v in results.values() if v is False)
    unreachable = sum(1 for v in results.values() if v is None)
    print_fn(
        f"Terminology validation: {valid}/{total} valid, "
        f"{invalid} not found, {unreachable} API unreachable"
    )
    if invalid:
        bad_codes = [code for (_, code), v in results.items() if v is False]
        print_fn(f"  Invalid codes (first 5): {bad_codes[:5]}")
