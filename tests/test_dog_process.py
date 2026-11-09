"""F2: a declared process (design_context.yaml, --process, the page's selector), the first interview question,
no process-specific guideline from a weak guess, and the process named in each weak-spot line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from dog_fixtures import edge_hole_plate, loose_arm_many
from typer.testing import CliRunner

from stepscribe.analysis import AnalyzeOptions
from stepscribe.api import analyze_full
from stepscribe.cli import app
from stepscribe.pack.design_context import apply_context, load_context
from stepscribe.ui import server, worker
from stepscribe.understanding.process import declared_process, rules
from stepscribe.understanding.questions import generate_questions
from stepscribe.understanding.weak_spots import process_tag, top_process

runner = CliRunner()


@pytest.fixture(scope="module")
def plate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return edge_hole_plate(tmp_path_factory.mktemp("plate"))


def analyse(path: Path, tmp_path: Path, context: str | None = None) -> Any:
    opts = AnalyzeOptions(no_timestamp=True, material="steel")
    if context is not None:
        ctx = tmp_path / "design_context.yaml"
        ctx.write_text(context, encoding="utf-8")
        apply_context(opts, load_context(ctx))
    return analyze_full(path, opts).report


def edge_lines(report: Any) -> list[Any]:
    return [w for w in report.understanding.weak_spots if w.category == "edge_distance"]


# ---- the words
@pytest.mark.parametrize(
    "word, label",
    [
        ("fdm", "fdm_3d_printed"),
        ("sheet", "sheet_metal"),
        ("cnc", "cnc_milled"),
        ("unknown", "unknown"),
        ("FDM", "fdm_3d_printed"),
        ("laser_or_waterjet", "laser_or_waterjet"),
        ("cnc milled", "cnc_milled"),
    ],
)
def test_the_declared_words_map_to_processes(word: str, label: str) -> None:
    assert declared_process(word) == label


def test_a_word_that_is_not_a_process_is_refused_in_the_context_file(tmp_path: Path) -> None:
    ctx = tmp_path / "c.yaml"
    ctx.write_text("process: welding\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be one of fdm, sheet, cnc, unknown"):
        load_context(ctx)


# ---- a declared process
def test_a_process_in_the_context_file_is_declared_and_named_in_the_line(
    plate: Path, tmp_path: Path
) -> None:
    report = analyse(plate, tmp_path, "process: cnc\n")
    process = report.parts[0].understanding.process
    assert process.source == "user" and process.ranked[0].label == "cnc_milled"
    lines = edge_lines(report)
    assert lines and all("[process: cnc milled, declared]" in w.message for w in lines)
    assert "1.5 x diameter" in lines[0].message  # the metal factor, said only for a metal process


def test_fdm_names_fdm_and_never_says_metal(plate: Path, tmp_path: Path) -> None:
    report = analyse(plate, tmp_path, "process: fdm\n")
    lines = edge_lines(report)
    assert lines and all("[process: fdm 3d printed, declared]" in w.message for w in lines)
    assert not any("metal" in (w.depends_on_assumption or "") for w in lines)
    assert "2.0 x diameter" in lines[0].message


def test_unknown_declared_gives_no_process_guideline_and_is_said(
    plate: Path, tmp_path: Path
) -> None:
    report = analyse(plate, tmp_path, "process: unknown\n")
    lines = edge_lines(report)
    assert lines and all("[process: not known, declared]" in w.message for w in lines)
    assert all("the general rule of thumb (process not declared)" in w.message for w in lines)
    assert not any("metal" in (w.depends_on_assumption or "") for w in lines)


# ---- a weak guess gives no process-specific guideline
def test_a_guess_below_075_gives_no_process_guideline_and_no_metal_wording(
    plate: Path, tmp_path: Path
) -> None:
    report = analyse(plate, tmp_path)
    part = report.parts[0]
    top = part.understanding.process.ranked[0]
    assert top.confidence < 0.75 and part.understanding.process.source == "inferred"
    proc, why = top_process(part)
    assert proc is None and "below 0.75" in why and "no process-specific guideline" in why
    lines = edge_lines(report)
    assert lines
    for w in lines:
        assert "metal factor" not in (w.depends_on_assumption or "")
        assert "metal factor" not in w.message
        assert "the general rule of thumb (process not declared)" in w.message
        assert "[process: not declared; no process-specific guideline]" in w.message
    assert process_tag(part) == " [process: not declared; no process-specific guideline]"


def test_a_guess_from_075_is_used_and_labelled_as_a_guess(plate: Path, tmp_path: Path) -> None:
    report = analyse(plate, tmp_path)
    part = report.parts[0]
    part.understanding.process.ranked[0].confidence = 0.8
    part.understanding.process.ranked[0].label = "cnc_milled"
    proc, why = top_process(part)
    assert proc == "cnc_milled" and "guessed, confidence 0.80" in why
    assert "[process: cnc milled, guessed, confidence 0.80]" in process_tag(part)
    assert rules()["guideline_min_confidence"] == 0.75


# ---- the command line
def test_the_process_option_declares_the_process(plate: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "pack",
            str(plate),
            "--out",
            str(tmp_path),
            "--no-images",
            "--process",
            "fdm",
            "--material",
            "steel",
        ],
    )
    assert result.exit_code == 0, result.output
    pack = next(tmp_path.glob("*_context_pack"))
    text = (pack / "05_understanding.md").read_text(encoding="utf-8")
    assert "[process: fdm 3d printed, declared]" in text and "metal factor" not in text


def test_the_command_line_wins_over_the_file(plate: Path, tmp_path: Path) -> None:
    ctx = tmp_path / "c.yaml"
    ctx.write_text("process: sheet\n", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "pack",
            str(plate),
            "--out",
            str(tmp_path),
            "--no-images",
            "--process",
            "cnc",
            "--context",
            str(ctx),
            "--material",
            "steel",
        ],
    )
    assert result.exit_code == 0, result.output
    pack = next(tmp_path.glob("*_context_pack"))
    text = (pack / "05_understanding.md").read_text(encoding="utf-8")
    assert "[process: cnc milled, declared]" in text and "sheet metal, declared" not in text


def test_a_bad_process_option_is_refused_plainly(plate: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["pack", str(plate), "--out", str(tmp_path), "--process", "welding"]
    )
    assert result.exit_code == 2 and "must be one of fdm, sheet, cnc, unknown" in result.output


# ---- the page
def test_the_page_has_a_process_selector_and_the_server_checks_it() -> None:
    page = (Path(server.__file__).parent / "index.html").read_text(encoding="utf-8")
    assert 'id="process"' in page and "process: $('process').value" in page
    assert server._params({"process": "FDM"})["process"] == "fdm"
    assert server._params({})["process"] is None
    with pytest.raises(server.BadRequest, match="process must be one of"):
        server._params({"process": "welding"})
    assert worker.job_options({"process": "sheet"}).extra["default_process"] == "sheet_metal"
    assert "default_process" not in worker.job_options({}).extra


# ---- the first question
def test_the_process_is_the_first_question_until_it_is_declared(tmp_path: Path) -> None:
    path = loose_arm_many(tmp_path, loose=3)
    report = analyse(path, tmp_path)
    questions = generate_questions(report, None, {}, None)
    assert questions and questions[0].kind == "process"
    declared = analyse(path, tmp_path, "process: cnc\n")
    assert all(q.kind != "process" for q in generate_questions(declared, None, {}, None))
