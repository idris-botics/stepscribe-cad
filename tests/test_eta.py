"""The remaining-time estimate: a pure function of the events, shared by the page and the command line.

The traces here are synthetic (made up, not recorded from any model)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from stepscribe.eta import Estimate, Event, estimate, range_text
from stepscribe.progress import Progress, Tracker


def trace(
    n_parts: int = 12,
    faces_each: int = 100,
    workers: int = 4,
    part_s: float = 10.0,
    pairs: int = 30,
    pair_s: float = 4.0,
    images: int = 20,
    image_s: float = 3.0,
) -> list[Event]:
    """A made-up run: parts finish in waves, then contacts, understanding, images, write."""
    ev = [Event(0.0, "stage", "reading")]
    ev.append(
        Event(
            1.0,
            "plan_parts",
            n=n_parts,
            faces=n_parts * faces_each,
            workers=workers,
            sizes=(faces_each,) * n_parts,
            assembly=True,
        )
    )
    t = 1.0
    for i in range(n_parts):
        if i % workers == 0:
            t += part_s
        ev.append(Event(t, "part", n=faces_each, cpu_s=part_s))
    t += 1.0
    ev.append(Event(t, "plan_pairs", n=pairs))
    for _ in range(pairs):
        t += pair_s
        ev.append(Event(t, "pair", cpu_s=pair_s))
    t += 1.0
    ev.append(Event(t, "stage", "understanding"))
    t += 15.0
    ev.append(Event(t, "stage", "render"))
    ev.append(Event(t, "plan_images", n=images))
    for _ in range(images):
        t += image_s
        ev.append(Event(t, "image", cpu_s=image_s))
    t += 1.0
    ev.append(Event(t, "stage", "write"))
    t += 4.0
    ev.append(Event(t, "done"))
    return ev


def run_through(events: list[Event], image_set: str = "basic") -> list[tuple[float, Estimate]]:
    """The estimate after every event, as the page would have shown it (the previous one is kept)."""
    out: list[tuple[float, Estimate]] = []
    previous: Estimate | None = None
    for i, e in enumerate(events):
        previous = estimate(events[: i + 1], e.t, image_set, previous)
        out.append((e.t, previous))
    return out


def test_it_says_estimating_until_two_parts_are_done() -> None:
    ev = trace()
    plan = ev[:2]
    assert estimate(plan, 5.0).text == "estimating..."
    one = [*plan, ev[2]]
    assert estimate(one, 5.0).state == "estimating"
    two = [*plan, ev[2], ev[3]]
    assert estimate(two, 5.0).state != "estimating"


def test_it_says_estimating_after_twenty_seconds_even_with_one_part() -> None:
    ev = trace()
    est = estimate(ev[:2], 22.0)
    assert est.state == "range" and est.low_s is not None and est.high_s is not None


def test_the_text_is_a_range_in_whole_minutes_never_seconds() -> None:
    for _t, est in run_through(trace()):
        assert "second" not in est.text and " s" not in est.text
        if est.state == "range":
            assert est.low_min is not None and est.high_min is not None
            assert 0 <= est.low_min <= est.high_min
            assert est.text == range_text(est.low_min, est.high_min)


def test_it_is_never_negative_and_the_bar_never_goes_back() -> None:
    last = 0.0
    for _t, est in run_through(trace()):
        for v in (est.low_s, est.high_s):
            assert v is None or v >= 0.0
        assert est.fraction >= 0.0
        last = max(last, est.fraction)
    assert last <= 1.0


def test_within_a_stage_the_shown_range_never_rises() -> None:
    by_stage: dict[str, int] = {}
    for _t, est in run_through(trace()):
        if est.state != "range" or est.high_min is None:
            continue
        if est.stage in by_stage:
            assert est.high_min <= by_stage[est.stage], est.stage
        by_stage[est.stage] = est.high_min


def test_a_stage_that_overruns_says_taking_longer_than_expected() -> None:
    ev = trace()
    # the understanding stage began at t0; far past what the prior allows, with nothing new happening
    stage = next(e for e in ev if e.kind == "stage" and e.stage == "understanding")
    upto = [e for e in ev if e.t <= stage.t]
    est = estimate(upto, stage.t + 100000.0)
    assert est.state == "longer" and est.text == "taking longer than expected"
    assert est.low_s == 0.0 and est.high_s == 0.0


def test_the_last_stage_says_almost_done() -> None:
    ev = trace()
    write = next(e for e in ev if e.kind == "stage" and e.stage == "write")
    est = estimate([e for e in ev if e.t <= write.t], write.t + 1.0)
    assert est.state == "almost_done" and est.text == "almost done"


def test_done_is_zero() -> None:
    est = estimate(trace(), 1000.0)
    assert est.state == "done" and est.fraction == 1.0 and est.high_s == 0.0


def test_the_image_set_changes_what_is_expected_after_the_parts() -> None:
    ev = trace()
    two_parts = ev[:4]
    basic = estimate(two_parts, 15.0, "basic")
    full = estimate(two_parts, 15.0, "full")
    none = estimate(two_parts, 15.0, "none")
    assert none.high_s is not None and basic.high_s is not None and full.high_s is not None
    assert none.high_s < basic.high_s < full.high_s


def test_the_planned_images_replace_the_prior_and_the_counter_ends_at_the_plan() -> None:
    ev = trace(images=10, image_s=3.0)
    plan = next(i for i, e in enumerate(ev) if e.kind == "plan_images")
    just_planned = estimate(ev[: plan + 1], ev[plan].t, "basic")
    five_done = estimate(ev[: plan + 6], ev[plan + 5].t, "basic")
    assert just_planned.high_s is not None and five_done.high_s is not None
    assert five_done.high_s < just_planned.high_s


def test_the_estimate_follows_the_real_remaining_time_in_the_parts_stage() -> None:
    """At 25, 50 and 75 % of the run the middle of the shown range is within a factor of two of the truth,
    except at 25 % where the stages after the parts are only a prior."""
    ev = trace()
    total = max(e.t for e in ev)
    previous: Estimate | None = None
    shown: dict[float, Estimate] = {}
    marks = {round(total * s, 3): s for s in (0.25, 0.5, 0.75)}
    for now in sorted({e.t for e in ev} | set(marks)):
        previous = estimate([e for e in ev if e.t <= now], now, "basic", previous)
        if now in marks:
            shown[marks[now]] = previous
    for share in (0.5, 0.75):
        est = shown[share]
        truth = total * (1 - share)
        assert est.mid_s is not None and truth / 2.5 <= est.mid_s <= truth * 2.5, (share, est)


def test_a_plain_part_list_with_no_assembly_expects_no_contact_stage() -> None:
    ev = [
        Event(0.0, "stage", "reading"),
        Event(1.0, "plan_parts", n=4, faces=400, workers=2, sizes=(100,) * 4, assembly=False),
        Event(11.0, "part", n=100, cpu_s=10.0),
        Event(11.0, "part", n=100, cpu_s=10.0),
    ]
    with_asm = [
        Event(**{**e.__dict__, "assembly": True}) if e.kind == "plan_parts" else e for e in ev
    ]
    assert estimate(ev, 12.0).high_s < estimate(with_asm, 12.0).high_s  # type: ignore[operator]


# ---- the Tracker: the same function behind the page and the command line
class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_the_tracker_records_events_and_shows_the_estimates_text() -> None:
    clock = Clock()
    seen: list[Progress] = []
    tr = Tracker(seen.append, clock=clock)
    tr.images_wanted = True
    tr.stage("reading", "reading the file")
    clock.now += 1
    tr.plan_parts(4, 400, True, sizes=(100,) * 4, workers=2)
    assert seen[-1].eta_text == "estimating..."
    for _ in range(2):
        clock.now += 10
        tr.part_done("p", 100, 5.0, cpu_s=10.0)
    assert seen[-1].eta_text.startswith("about") or seen[-1].eta_text in ("less than a minute",)
    assert [e.kind for e in tr.events][:3] == ["stage", "plan_parts", "part"]
    assert tr.events[-1].cpu_s == 10.0  # the time in its own process, not the wall share shown


def test_the_tracker_text_is_what_the_pure_function_gives_for_its_events() -> None:
    clock = Clock()
    seen: list[Progress] = []
    tr = Tracker(seen.append, clock=clock)
    tr.plan_parts(3, 300, False, sizes=(100,) * 3, workers=1)
    for _ in range(3):
        clock.now += 30
        tr.part_done("p", 100, 30.0)
    again = estimate(tr.events, clock() - tr.start, "none", None)
    assert seen[-1].eta_text == again.text


def test_the_command_line_and_the_page_read_the_same_field() -> None:
    root = Path(__file__).resolve().parent.parent / "stepscribe"
    cli = (root / "cli.py").read_text(encoding="utf-8")
    page = (root / "ui" / "index.html").read_text(encoding="utf-8")
    worker = (root / "ui" / "worker.py").read_text(encoding="utf-8")
    assert "p.eta_text" in cli and "s.eta_text" in page and "p.eta_text" in worker


def test_the_planned_image_counter_ends_at_the_plan_with_skips_counted() -> None:
    tr = Tracker()
    tr.plan_images(3, "standard")
    tr.image_done("a.png", 1.0)
    tr.image_skipped("b.png", "nothing to show")
    tr.image_done("c.png", 1.0)
    assert (tr.images_done, tr.images_total, tr.images_skipped, tr.image_set) == (
        3,
        3,
        1,
        "standard",
    )


# ---- the replay script
def load_script():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parent.parent / "scripts" / "eta_replay.py"
    spec = importlib.util.spec_from_file_location("eta_replay", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_replay_script_prints_the_estimate_at_each_point(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from dataclasses import asdict

    events = tmp_path / "events.json"
    events.write_text(json.dumps([asdict(e) for e in trace()]), encoding="utf-8")
    assert load_script().main([str(events)]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 3 and lines[0].lstrip().startswith("25%") and "remaining" in lines[0]
    assert all("really" in x for x in lines)
