"""F1: the headline never states the degrees of freedom as fact when many rigid groups have no joint evidence."""

from __future__ import annotations

import pytest
from dog_fixtures import loose_arm_many

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.understanding.unjointed import (
    many_unjointed,
    unjointed_groups,
    unjointed_share,
    unjointed_text,
)


@pytest.fixture(scope="module")
def many(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    path = loose_arm_many(tmp_path_factory.mktemp("many"), loose=6)
    return analyze_full(path, AnalyzeOptions(no_timestamp=True, material="steel")).report


@pytest.fixture(scope="module")
def few(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    path = loose_arm_many(tmp_path_factory.mktemp("few"), loose=0)
    return analyze_full(path, AnalyzeOptions(no_timestamp=True, material="steel")).report


def test_the_fixture_has_many_groups_without_a_joint(many) -> None:  # type: ignore[no-untyped-def]
    kin = many.understanding.kinematics
    free, total = unjointed_groups(kin)
    assert free >= 6 and free / total > 0.4 and many_unjointed(kin)


def test_the_summary_says_how_many_groups_have_no_joint_and_that_the_dof_may_be_higher(
    many,
) -> None:  # type: ignore[no-untyped-def]
    kin = many.understanding.kinematics
    free, total = unjointed_groups(kin)
    text = many.understanding.summary
    assert f"{free} of {total} rigid groups have no joint evidence" in text
    assert "the real DOF may be higher" in text
    assert "single revolute joint mechanism" not in text and "1 DOF" not in text
    assert unjointed_text(kin) in text


def test_the_kinematics_description_gives_the_dof_as_a_lower_bound(many) -> None:  # type: ignore[no-untyped-def]
    kin = many.understanding.kinematics
    assert "from the joints found" in kin.description and "may be higher" in kin.description
    assert "estimated 2 degree" not in kin.description


def test_the_counts_carry_no_confidence_and_each_joint_is_listed_once_with_its_own(many) -> None:  # type: ignore[no-untyped-def]
    kin = many.understanding.kinematics
    text = many.understanding.summary
    counts = unjointed_text(kin)
    assert counts in text
    assert "confidence" not in counts and not text.split(counts)[0].rstrip().endswith("(")
    for j in kin.joints:
        phrase = f"{j.id} {j.kind} about"
        assert text.count(phrase) <= 1
    if len(kin.joints) <= 4:
        assert all(f"(confidence {j.confidence:.2f})" in text for j in kin.joints)


def test_the_share_without_joints_still_caps_a_mechanism_type_guess_internally(many) -> None:  # type: ignore[no-untyped-def]
    kin = many.understanding.kinematics
    cap = round(1.0 - unjointed_share(kin), 2)
    if kin.headline_confidence is not None:
        assert kin.headline_confidence <= cap + 1e-9


def test_a_model_with_few_groups_without_joints_keeps_its_wording(few) -> None:  # type: ignore[no-untyped-def]
    kin = few.understanding.kinematics
    assert not many_unjointed(kin)
    assert "the real DOF may be higher" not in few.understanding.summary
    assert "from the joints found" not in kin.description and "at least" not in kin.description
