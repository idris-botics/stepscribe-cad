"""Rigid groups that no joint reaches: every output finishes and says so. A seeded property test drops joints
from generated models (a fast subset in the normal run, the full set marked slow) and runs every writer and
checker on what is left."""

from __future__ import annotations

import json
import queue as queue_module
import random
from pathlib import Path
from typing import Any

import pytest
from test_image_failures import build_loose_arm, needs_gl
from typer.testing import CliRunner

from stepscribe import robot_check
from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.cli import app
from stepscribe.exporter import export
from stepscribe.io.multi import InputLimits, expand_inputs
from stepscribe.pack.robot import build_robot, unconnected_group_ids
from stepscribe.pack.writer import write_pack
from stepscribe.progress import Progress, Tracker
from stepscribe.render import plan as image_plan
from stepscribe.ui import worker

runner = CliRunner()


@pytest.fixture(scope="module")
def loose_arm(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_loose_arm(tmp_path_factory.mktemp("loose_arm_regression"))


def unconnected(analysis: Any) -> list[str]:
    robot = build_robot(analysis.report)
    return [] if robot is None else unconnected_group_ids(robot)


# ------------------------------------------------------------------------------ the regression
def test_the_pack_writer_finishes_and_says_which_groups_the_urdf_leaves_out(
    loose_arm: Path, tmp_path: Path
) -> None:
    analysis = analyze_full(loose_arm, AnalyzeOptions(no_timestamp=True, material="steel"))
    groups = unconnected(analysis)
    assert len(groups) >= 2
    folder = write_pack(analysis, tmp_path, images=False)
    urdf = (folder / "robot.urdf").read_text(encoding="utf-8")
    assert "Not written" in urdf and all(g in urdf.split("-->")[0] for g in groups)
    robot = json.loads((folder / "robot.json").read_text(encoding="utf-8"))
    by_id = {link["id"]: link for link in robot["links"]}
    for g in groups:  # robot.json lists every group with its mass and centre of mass
        assert by_id[g]["mass_g"] and by_id[g]["com_mm"] and by_id[g]["inertia_g_mm2"]
    readme = (folder / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "Rigid groups no joint reaches" in readme and groups[0] in readme
    assert (folder / "data" / "report.json").is_file()


def test_validate_robot_passes_and_says_the_groups_are_left_out_on_purpose(
    loose_arm: Path, tmp_path: Path
) -> None:
    analysis = analyze_full(loose_arm, AnalyzeOptions(no_timestamp=True, material="steel"))
    folder = write_pack(analysis, tmp_path, images=False)
    report = robot_check.validate(folder, n_random=2)
    assert report.structurally_valid, robot_check.format_report(report)
    notes = [f for f in report.structural if f.code == "S055"]
    assert len(notes) == 1 and notes[0].severity == "info" and "on purpose" in notes[0].message
    assert "S055" in robot_check.format_report(
        report
    ) or "left them out" in robot_check.format_report(report)


def test_the_export_path_finishes(loose_arm: Path, tmp_path: Path) -> None:
    result = export(
        loose_arm,
        tmp_path,
        AnalyzeOptions(no_timestamp=True, material="steel"),
        images=False,
        make_zip=False,
    )
    assert Path(result.folder).is_dir()


def test_the_ui_path_finishes(loose_arm: Path, tmp_path: Path) -> None:
    q: queue_module.Queue[dict[str, Any]] = queue_module.Queue()
    job = {"path": str(loose_arm), "out": str(tmp_path), "images": False, "material": "steel"}
    worker.run_job(job, q)
    msgs = []
    while not q.empty():
        msgs.append(q.get())
    assert not [m for m in msgs if m["type"] == "error"], msgs
    done = [m for m in msgs if m["type"] == "done"]
    assert len(done) == 1 and (Path(done[0]["pack"]) / "robot.urdf").is_file()


def test_the_command_line_finishes(loose_arm: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["pack", str(loose_arm), "--out", str(tmp_path), "--material", "steel", "--no-images"],
    )
    assert result.exit_code == 0, result.output
    pack = next(tmp_path.glob("*_context_pack"))
    assert (pack / "robot.urdf").is_file() and "Not written" in (pack / "robot.urdf").read_text(
        encoding="utf-8"
    )


# ------------------------------------------------------------------------ the property test
KINDS = {
    "arm": ("two_link_arm", None),
    "multi_file_arm": ("multi_arm", "folder"),
    "branched": ("mini_mobile_manipulator", None),
    "one_joint": ("linear_slide", None),
    "no_joints": ("two_plates_assembly", None),
}
SEEDS = (1, 2, 3, 4)


def fresh(kind: str, step_files: Any, tmp_path: Path) -> Any:
    name, how = KINDS[kind]
    opts = AnalyzeOptions(no_timestamp=True, material="steel")
    if how == "folder":
        files = expand_inputs([step_files[name]], InputLimits(), tmp_path / "in")
        return analyze_full(files, opts, None, "multi")
    return analyze_full(step_files[name], opts)


def keep_subset(n: int, seed: int) -> list[int]:
    """The joints that stay connected: a seeded random subset (possibly none, possibly all)."""
    rng = random.Random(seed)
    return sorted(rng.sample(range(n), rng.randint(0, n))) if n else []


def one_trial(
    kind: str, seed: int, image_set: str, step_files: Any, tmp_path: Path, images: bool
) -> None:
    analysis = fresh(kind, step_files, tmp_path)
    kin = analysis.report.understanding.kinematics if analysis.report.understanding else None
    saved = list(kin.joints) if kin is not None else []
    if kin is not None:
        kin.joints = [saved[i] for i in keep_subset(len(saved), seed)]
    try:
        events: list[Progress] = []
        tracker = Tracker(events.append)
        tracker.images_wanted = images
        expected = image_plan.plan_images(analysis, image_set) if images else None
        folder = write_pack(
            analysis, tmp_path / "out", images=images, tracker=tracker, image_set=image_set
        )
        if images and expected is not None and (folder / "images").is_dir():
            assert tracker.images_total == expected.total
            assert tracker.images_done == tracker.images_total
            made = [r for r in expected.names() if (folder / r).is_file()]
            assert len(made) + tracker.images_skipped == tracker.images_total
        assert (folder / "data" / "report.json").is_file()
        if (folder / "robot.urdf").is_file():
            report = robot_check.validate(folder, n_random=1)
            assert report.structurally_valid, robot_check.format_report(report)
    finally:
        if kin is not None:
            kin.joints = saved


@pytest.mark.parametrize("kind", list(KINDS))
def test_random_joint_subsets_fast(kind: str, step_files: Any, tmp_path: Path) -> None:
    """One seed per model kind, no images (the writers, validate-robot)."""
    one_trial(kind, SEEDS[0], "basic", step_files, tmp_path, images=False)


@needs_gl
@pytest.mark.parametrize("kind", ["arm", "branched"])
def test_random_joint_subsets_with_basic_images(kind: str, step_files: Any, tmp_path: Path) -> None:
    one_trial(kind, SEEDS[1], "basic", step_files, tmp_path, images=True)


@needs_gl
@pytest.mark.slow
@pytest.mark.parametrize("image_set", ["basic", "standard", "full"])
@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("kind", list(KINDS))
def test_random_joint_subsets_full(
    kind: str, seed: int, image_set: str, step_files: Any, tmp_path: Path
) -> None:
    one_trial(kind, seed, image_set, step_files, tmp_path, images=True)
