"""The one schema bump (0.7.0) is planned in docs/schema_0_7_0.md: what #29 adds is in the schema, and the version
and the document's status move together."""

from __future__ import annotations

import json
import re
from pathlib import Path

from stepscribe.models.schema import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "docs" / "schema_0_7_0.md").read_text(encoding="utf-8")
SCHEMA = json.loads((ROOT / "schema" / "report.schema.json").read_text(encoding="utf-8"))


def test_the_status_and_the_version_move_together() -> None:
    status = re.search(r"^Status: (.+)$", DOC, re.MULTILINE)
    assert status is not None
    pending = status.group(1).startswith("pending")
    assert pending or status.group(1) == "released in 0.7.0"
    assert (SCHEMA_VERSION == "0.6.0") if pending else (SCHEMA_VERSION == "0.7.0")


def test_what_this_pull_request_adds_is_in_the_schema_and_is_optional() -> None:
    section = DOC.split("## Added by #29", 1)[1].split("\n## ", 1)[0]
    assert "`Hole.thread`" in section and "`serrated`" in section
    defs = SCHEMA["$defs"]
    assert "thread" in defs["Hole"]["properties"] and "thread" not in defs["Hole"].get(
        "required", []
    )
    assert "ModelledThread" in defs
    assert "serrated" in json.dumps(defs["ShapeClass"])


def test_the_document_lists_the_fields_the_other_pull_requests_add() -> None:
    for item in ("MassProperties.designer_mass", "designer_mass", "MassProperties.density_range"):
        assert item in DOC
    assert re.search(r"#24", DOC) and re.search(r"#25", DOC)


def test_what_24_and_25_added_is_in_the_schema_too() -> None:
    defs = SCHEMA["$defs"]
    assert "DesignerMass" in defs and "DensityRange" in defs
    mass = defs["MassProperties"]["properties"]
    assert "designer_mass" in mass and "density_range" in mass
    assert "designer_mass" in json.dumps(mass["material_source"])
    assert "designer_mass" not in defs["MassProperties"].get("required", [])
