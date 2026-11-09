"""F3: a name alone never makes a holder, mount, bracket, plate, cover, case, housing or adapter a motor; roles
from a name are low and labelled "from the name"; a servo-sized opening is geometry evidence for a servo mount."""

from __future__ import annotations

from typing import Any

import pytest
from dog_fixtures import named_parts

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.understanding.function import cfg, name_role_hits

NAMED_ROLES = 0.35  # roles.yaml part_roles.name_only_cap


@pytest.fixture(scope="module")
def parts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    path = named_parts(tmp_path_factory.mktemp("named"))
    report = analyze_full(path, AnalyzeOptions(no_timestamp=True, material="steel")).report
    return {p.name.split(":")[0]: p for p in report.parts}


def roles(part: Any) -> dict[str, Any]:
    return {r.label: r for r in part.understanding.roles}


def test_a_servo_holder_is_not_a_motor(parts: dict[str, Any]) -> None:
    held = roles(parts["main servo holder"])
    assert "motor" not in held
    assert all(
        r.confidence <= NAMED_ROLES + 1e-9
        for r in held.values()
        if all(e.code.startswith("name:") for e in r.evidence)
    )


@pytest.mark.parametrize(
    "name",
    [
        "main servo holder",
        "servo mount",
        "servo bracket",
        "servo plate",
        "servo cover",
        "servo case",
        "servo housing",
        "servo adapter",
        "MG996 Servo Housing",
        "servo_horn_adapter",
    ],
)
def test_a_holder_word_blocks_the_motor_role_from_a_name(name: str) -> None:
    assert "motor" not in name_role_hits([name], cfg())


def test_without_a_holder_word_the_name_still_suggests_a_motor_but_low_and_labelled(
    parts: dict[str, Any],
) -> None:
    assert name_role_hits(["servo"], cfg()).get("motor") == "servo"
    connector = roles(parts["mg90 connector hole"])
    assert "motor" in connector
    motor = connector["motor"]
    assert motor.confidence <= NAMED_ROLES + 1e-9
    assert all(e.code.startswith("name:") for e in motor.evidence)
    assert all(e.text.startswith("from the name:") for e in motor.evidence)


def test_every_name_derived_role_is_labelled_and_capped(parts: dict[str, Any]) -> None:
    for part in parts.values():
        for role in part.understanding.roles:
            named = [e for e in role.evidence if e.code.startswith("name:")]
            assert all(e.text.startswith("from the name:") for e in named)
            if role.evidence and all(e.code.startswith("name:") for e in role.evidence):
                assert role.confidence <= NAMED_ROLES + 1e-9


def test_a_servo_sized_opening_gives_servo_mount_likely_from_geometry(
    parts: dict[str, Any],
) -> None:
    got = roles(parts["servo bracket pocket"])
    assert "servo_mount" in got and "motor" not in got
    mount = got["servo_mount"]
    assert any(e.code == "geometry:servo_pocket" for e in mount.evidence)
    text = " ".join(e.text for e in mount.evidence)
    assert "servo mount (likely)" in text and "micro servo" in text
    assert 0.3 < mount.confidence < 0.75


def test_an_opening_with_clearance_round_a_servo_body_still_gives_servo_mount(
    parts: dict[str, Any],
) -> None:
    """The dog's main servo holder has a 24.7 x 13.2 mm opening: a micro servo (22.5 x 12 mm) plus clearance."""
    got = roles(parts["clearance holder"])
    assert "servo_mount" in got and "motor" not in got
    assert any(
        "13.2 x 24.7 mm matches a micro servo" in e.text for e in got["servo_mount"].evidence
    )


def test_a_role_from_the_name_alone_says_so_where_it_is_printed(parts: dict[str, Any]) -> None:
    from stepscribe.understanding.describe import _role_label, understanding_sentences

    part = parts["mg90 connector hole"]
    top = part.understanding.roles[0]
    assert top.label == "motor"  # a servo model in the name; no holder word
    assert _role_label(top) == "motor (from the name)"
    assert any("from the name" in s for s in understanding_sentences(part))
    geometric = parts["servo bracket pocket"].understanding.roles[0]
    assert "(from the name)" not in _role_label(geometric)


def test_an_opening_of_another_size_gives_no_servo_mount(parts: dict[str, Any]) -> None:
    assert "servo_mount" not in roles(parts["frame plate"])
    assert "servo_mount" not in roles(parts["main servo holder"])


def test_the_sizes_are_a_sourced_range_not_a_product() -> None:
    sizes = cfg()["servo_pocket"]
    assert "hobby servo" in sizes["source"] and len(sizes["sizes"]) >= 2
