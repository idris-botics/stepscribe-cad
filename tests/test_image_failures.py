"""One failing image never stops the pack; the planned image total is the number of images made or
skipped; a non-image failure is reported readably. The models are generated; nothing outside the repo."""

from __future__ import annotations

import json
import queue as queue_module
from pathlib import Path
from typing import Any

import pytest
from assembly_fixtures import Node, write_assembly
from assembly_fixtures_u import X_AXIS, bearing_608
from build123d import Box, Cylinder, Location, Pos

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.io.multi import InputLimits, expand_inputs
from stepscribe.pack.robot import build_robot
from stepscribe.pack.urdf import build_urdf
from stepscribe.pack.writer import pack_folder, write_pack
from stepscribe.progress import Progress, Tracker
from stepscribe.render import plan as image_plan
from stepscribe.render.raster import rendering_available
from stepscribe.robot_check.model import parse_urdf
from stepscribe.ui import worker

needs_gl = pytest.mark.skipif(
    not rendering_available(), reason="off-screen rendering is not available on this machine"
)


# ---------------------------------------------------------------------------------------- fixture
def build_loose_arm(out: Path) -> Path:
    """A two-link arm with two loose blocks that nothing touches: rigid groups no joint connects."""
    base = Pos(0, 0, 22.5) * Box(40, 30, 45) - Pos(0, 0, 30) * X_AXIS * Cylinder(11, 50)
    arm1 = (
        Box(10, 30, 90)
        - Pos(0, 0, -37) * X_AXIS * Cylinder(4, 12)
        - Pos(0, 0, 28) * X_AXIS * Cylinder(11, 12)
    )
    arm2 = Box(10, 30, 63) - Pos(0, 0, -26) * X_AXIS * Cylinder(4, 12)
    protos = {
        "Base": base,
        "Bearing608": bearing_608(),
        "ShaftA": Cylinder(4, 42),
        "ShaftB": Cylinder(4, 20),
        "ArmLink1": arm1,
        "ArmLink2": arm2,
        "LooseBlock": Box(20, 20, 20),
    }
    root = Node(
        "LooseArm",
        children=[
            Node("Base", "Base", Location()),
            Node("Bearing1", "Bearing608", Pos(0, 0, 30) * X_AXIS),
            Node("Shaft1", "ShaftA", Pos(11, 0, 30) * X_AXIS),
            Node("Arm1", "ArmLink1", Pos(27, 0, 67)),
            Node("Bearing2", "Bearing608", Pos(27, 0, 95) * X_AXIS),
            Node("Shaft2", "ShaftB", Pos(34, 0, 95) * X_AXIS),
            Node("Arm2", "ArmLink2", Pos(39, 0, 121)),
            Node("LooseOne", "LooseBlock", Pos(300, 300, 10)),
            Node("LooseTwo", "LooseBlock", Pos(-300, 250, 10)),
        ],
    )
    return write_assembly(out / "loose_arm.step", protos, root)


@pytest.fixture(scope="session")
def loose_arm(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_loose_arm(tmp_path_factory.mktemp("loose_arm"))


def analysis_of(path: Path | list[Path], name: str | None = None, tracker: Tracker | None = None):  # type: ignore[no-untyped-def]
    return analyze_full(path, AnalyzeOptions(no_timestamp=True, material="steel"), tracker, name)


# ---------------------------------------------------------------- the cause: unconnected links
def test_the_urdf_leaves_out_rigid_groups_no_joint_reaches(loose_arm: Path) -> None:
    report = analysis_of(loose_arm).report
    robot = build_robot(report)
    assert robot is not None
    joined = {robot["base_link"], *(j["child"] for j in robot["joints"])}
    loose = [link["id"] for link in robot["links"] if link["id"] not in joined]
    assert loose, "the fixture must have rigid groups that no joint connects"
    assert any(link["mass_g"] is not None for link in robot["links"] if link["id"] in loose)
    text = build_urdf(robot)  # this raised KeyError on the first loose group that has a mass
    urdf = parse_urdf(text)
    names = {link.name for link in urdf.links}
    assert names == joined and not names & set(loose)
    assert all(j.parent in names and j.child in names for j in urdf.joints)
    assert "Not written" in text and all(link_id in text for link_id in loose)
    assert "robot.json" in text  # where the left-out groups are listed with their mass


def test_robot_json_still_lists_every_rigid_group(loose_arm: Path) -> None:
    robot = build_robot(analysis_of(loose_arm).report)
    assert robot is not None and len(robot["links"]) > len(robot["joints"]) + 1


# ------------------------------------------------------------------------- failure isolation
def drawn(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in (folder / "images").rglob("*.png"))


def finished(folder: Path) -> None:
    for name in ("00_READ_ME_FIRST.md", "01_overview.md", "context_pack.md", "data/report.json"):
        assert (folder / name).is_file(), name


@needs_gl
def test_one_failing_extra_image_leaves_the_rest_and_is_listed(
    loose_arm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stepscribe.render import skeleton_view

    def boom(*_a: Any, **_k: Any) -> Any:
        raise KeyError("L2")

    monkeypatch.setattr(skeleton_view, "axes_on_model", boom)
    analysis = analysis_of(loose_arm)
    folder = write_pack(analysis, tmp_path, images=True, image_set="full")
    finished(folder)
    files = drawn(folder)
    assert "images/assembly_iso.png" in files and "images/link_map.png" in files
    assert "images/kinematic_axes.png" not in files
    warnings = [w for w in analysis.report.warnings if w.startswith("image not drawn:")]
    assert any("kinematic_axes.png" in w and "KeyError" in w for w in warnings)
    index = (folder / "images" / "INDEX.md").read_text(encoding="utf-8")
    assert "Not drawn" in index and "KeyError" in index
    readme = (folder / "00_READ_ME_FIRST.md").read_text(encoding="utf-8")
    assert "Images not drawn" in readme and "kinematic_axes.png" in readme
    report = json.loads((folder / "data" / "report.json").read_text(encoding="utf-8"))
    assert any("image not drawn" in w for w in report["warnings"])


@needs_gl
def test_a_failing_base_image_is_skipped_and_the_basic_set_still_finishes(
    loose_arm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stepscribe import render

    def boom(*_a: Any, **_k: Any) -> Any:
        raise ValueError("cannot explode")

    monkeypatch.setattr(render, "apply_explode", boom)
    analysis = analysis_of(loose_arm)
    folder = write_pack(analysis, tmp_path, images=True, image_set="basic")
    finished(folder)
    files = drawn(folder)
    assert "images/assembly_exploded.png" not in files
    assert {
        "images/assembly_iso.png",
        "images/assembly_front.png",
        "images/kinematics_iso.png",
    } <= set(files)
    assert any("assembly_exploded.png" in w for w in analysis.report.warnings)
    assert "assembly_exploded.png" in (folder / "images" / "INDEX.md").read_text(encoding="utf-8")


@needs_gl
def test_a_failing_part_image_does_not_stop_the_other_parts(
    loose_arm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stepscribe import render

    analysis = analysis_of(loose_arm)
    first = render.rank_parts([ap.part for ap in analysis.parts])[0].id
    real = render.panel_lines

    def flaky(part: Any) -> Any:
        if part.id == first:
            raise RuntimeError("bad part")
        return real(part)

    monkeypatch.setattr(render, "panel_lines", flaky)
    folder = write_pack(analysis, tmp_path, images=True, image_set="basic")
    finished(folder)
    files = drawn(folder)
    assert f"images/parts/{first}_iso.png" not in files
    assert any(f.startswith("images/parts/") and first not in f for f in files)
    assert any(first in w and "RuntimeError" in w for w in analysis.report.warnings)


# ------------------------------------------------------------------ the planned total is the truth
def run_counted(analysis: Any, tmp_path: Path, image_set: str) -> tuple[Tracker, Path, list[str]]:
    events: list[Progress] = []
    tracker = Tracker(events.append)
    tracker.images_wanted = True
    folder = write_pack(analysis, tmp_path, images=True, tracker=tracker, image_set=image_set)
    return tracker, folder, [e.message for e in events]


def multi_arm_files(step_files: Any, tmp_path: Path) -> list[Path]:
    return expand_inputs([step_files["multi_arm"]], InputLimits(), tmp_path / "in")


CASES = ["single_part", "assembly", "robot_arm", "multi_file_arm", "loose_arm"]


def build_analysis(case: str, step_files: Any, loose_arm: Path, tmp_path: Path) -> Any:
    if case == "single_part":
        return analysis_of(step_files["plate_4xM3"])
    if case == "assembly":
        return analysis_of(step_files["two_plates_assembly"])
    if case == "robot_arm":
        return analysis_of(step_files["two_link_arm"])
    if case == "loose_arm":
        return analysis_of(loose_arm)
    return analysis_of(multi_arm_files(step_files, tmp_path), "multi")


@needs_gl
@pytest.mark.parametrize("image_set", ["basic", "standard", "full"])
@pytest.mark.parametrize("case", CASES)
def test_the_planned_total_is_what_was_made_plus_what_was_skipped(
    case: str, image_set: str, step_files: Any, loose_arm: Path, tmp_path: Path
) -> None:
    analysis = build_analysis(case, step_files, loose_arm, tmp_path)
    expected = image_plan.plan_images(analysis, image_set)  # the plan, before anything is drawn
    tracker, folder, messages = run_counted(analysis, tmp_path / "out", image_set)
    assert tracker.images_total == expected.total > 0
    assert tracker.images_done == tracker.images_total  # the counter ends at the total
    made = [rel for rel in expected.names() if (folder / rel).is_file()]
    assert len(made) + tracker.images_skipped == tracker.images_total
    shown = [m for m in messages if m.startswith(("rendered ", "skipped "))]
    assert len(shown) == tracker.images_total
    assert not any(
        int(m.split("(")[-1].split("/")[0]) > tracker.images_total
        for m in shown
        if m.startswith("rendered ")
    )
    finished(folder)


def test_the_caps_are_in_the_plan(step_files: Any, loose_arm: Path) -> None:
    from stepscribe.render.extra_images import MAX_EXTRA_IMAGES, MAX_PARTS_PER_TYPE

    plan = image_plan.plan_images(analysis_of(loose_arm), "full")
    assert all(len(v) <= MAX_PARTS_PER_TYPE for v in plan.extra.values())
    assert sum(len(v) for v in plan.extra.values()) <= MAX_EXTRA_IMAGES
    assert len(plan.names()) == len(set(plan.names())) == plan.total


# ----------------------------------------------------------------- a failure outside the images
def run_ui_job(step: Path, out: Path, monkeypatch: pytest.MonkeyPatch, fail: str) -> dict[str, Any]:
    from stepscribe.pack import writer

    def boom(*_a: Any, **_k: Any) -> Any:
        raise KeyError("L4")

    monkeypatch.setattr(writer, fail, boom) if fail != "urdf_text" else monkeypatch.setattr(
        "stepscribe.pack.urdf.urdf_text", boom
    )
    q: queue_module.Queue[dict[str, Any]] = queue_module.Queue()
    job = {"path": str(step), "out": str(out), "images": False, "material": "steel"}
    worker.run_job(job, q)
    msgs = []
    while not q.empty():
        msgs.append(q.get())
    errors = [m for m in msgs if m["type"] == "error"]
    assert len(errors) == 1, msgs
    return errors[0]


def test_the_ui_error_after_the_text_pack_says_it_was_kept(
    loose_arm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    err = run_ui_job(loose_arm, tmp_path, monkeypatch, "urdf_text")
    assert "\n" not in err["message"] and "KeyError: 'L4'" in err["message"]
    assert err["message"].startswith("The run stopped while writing the pack files.")
    assert "text pack was already written and is kept" in err["saved"]
    assert "robot.urdf" in err["saved"] and "nothing is saved" not in err["saved"].lower()
    log = Path(err["log"])
    assert log.is_file() and "Traceback" in log.read_text(encoding="utf-8")
    assert "KeyError" in log.read_text(encoding="utf-8")
    assert (pack_folder_of(tmp_path) / "data" / "report.json").is_file()


def test_the_ui_error_before_anything_was_written_says_nothing_was_saved(
    loose_arm: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    err = run_ui_job(loose_arm, tmp_path, monkeypatch, "build_sections")
    assert err["saved"] in ("Nothing was saved.",) or "partial pack" in err["saved"]
    assert err["log"] and Path(err["log"]).is_file()


def pack_folder_of(out: Path) -> Path:
    found = [p for p in out.iterdir() if p.is_dir() and p.name.endswith("_context_pack")]
    assert len(found) == 1
    return found[0]


def test_pack_folder_is_where_the_pack_is_written(loose_arm: Path, tmp_path: Path) -> None:
    analysis = analysis_of(loose_arm)
    folder = write_pack(analysis, tmp_path, images=False)
    assert pack_folder(analysis, tmp_path) == folder
