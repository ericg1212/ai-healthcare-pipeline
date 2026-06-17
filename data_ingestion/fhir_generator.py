# Copyright (c) 2026 Eric Grynspan. All rights reserved.
import subprocess
import sys
from pathlib import Path

SYNTHEA_JAR = Path(__file__).parent / "synthea.jar"
OUTPUT_DIR = Path(__file__).parent.parent / "synthetic_data"


def generate(n_patients: int = 200, seed: int = 42) -> list[Path]:
    OUTPUT_DIR.mkdir(exist_ok=True)

    subprocess.run(
        [
            "java", "-jar", str(SYNTHEA_JAR),
            "--exporter.baseDirectory", str(OUTPUT_DIR),
            "--exporter.hospital.fhir.export", "false",
            "--exporter.practitioner.fhir.export", "false",
            "-p", str(n_patients),
            "-s", str(seed),
            "Massachusetts",
        ],
        check=True,
    )

    return sorted((OUTPUT_DIR / "fhir").glob("*.json"))


if __name__ == "__main__":
    files = generate()
    print(f"Generated {len(files)} FHIR bundles → {OUTPUT_DIR / 'fhir'}")
    for f in files[:3]:
        print(f"  {f.name}")
    if len(files) > 3:
        print(f"  ... and {len(files) - 3} more")
    sys.exit(0)
