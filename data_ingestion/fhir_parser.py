# Copyright (c) 2026 Eric Grynspan. All rights reserved.
import json
from pathlib import Path


def extract_id(reference: str) -> str:
    return reference.split(":")[-1]


def parse_patient(resource: dict) -> dict:
    return {
        "patient_id": resource["id"],
        "birth_date": resource["birthDate"],
        "gender": resource["gender"],
        "state": resource["address"][0]["state"],
    }


def parse_condition(resource: dict, patient_id: str) -> dict:
    return {
        "patient_id": patient_id,
        "code": resource["code"]["coding"][0]["code"],
        "description": resource["code"]["coding"][0]["display"],
        "onset_date": resource.get("onsetDateTime", "")[:10],
    }


def parse_medication(resource: dict, patient_id: str) -> dict:
    med = resource.get("medicationCodeableConcept")
    if not med:
        return None
    return {
        "patient_id": patient_id,
        "code": med["coding"][0]["code"],
        "description": med["coding"][0]["display"],
        "start_date": resource.get("authoredOn", "")[:10],
    }


def parse_encounter(resource: dict, patient_id: str) -> dict:
    return {
        "patient_id": patient_id,
        "encounter_id": resource["id"],
        "encounter_type": resource["type"][0]["coding"][0]["display"],
        "start_date": resource["period"]["start"][:10],
        "end_date": resource["period"].get("end", "")[:10],
    }


def parse_bundle(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        bundle = json.load(f)

    person = []
    conditions = []
    medications = []
    encounters = []

    for entry in bundle["entry"]:
        resource = entry["resource"]
        rtype = resource["resourceType"]

        if rtype == "Patient":
            person.append(parse_patient(resource))
        elif rtype == "Condition":
            pid = extract_id(resource["subject"]["reference"])
            conditions.append(parse_condition(resource, pid))
        elif rtype == "MedicationRequest":
            pid = extract_id(resource["subject"]["reference"])
            med = parse_medication(resource, pid)
            if med:
                medications.append(med)
        elif rtype == "Encounter":
            pid = extract_id(resource["subject"]["reference"])
            encounters.append(parse_encounter(resource, pid))

    return {
        "person": person,
        "conditions": conditions,
        "medications": medications,
        "encounters": encounters,
    }


def parse_all(fhir_dir: Path) -> dict:
    all_persons = []
    all_conditions = []
    all_medications = []
    all_encounters = []

    for path in sorted(fhir_dir.glob("*.json")):
        result = parse_bundle(path)
        all_persons.extend(result["person"])
        all_conditions.extend(result["conditions"])
        all_medications.extend(result["medications"])
        all_encounters.extend(result["encounters"])

    return {
        "person": all_persons,
        "conditions": all_conditions,
        "medications": all_medications,
        "encounters": all_encounters,
    }


if __name__ == "__main__":
    fhir_dir = Path(__file__).parent.parent / "synthetic_data" / "fhir"
    results = parse_all(fhir_dir)
    for k, v in results.items():
        print(f"{k}: {len(v)} records")
