# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 idris sadiq
"""Compare our mass and inertia estimates with the ``<inertial>`` values of an existing URDF.

Per link: the mass ratio (ours / theirs) and the ratios of the sorted principal moments about the centre
of mass (the eigenvalues of each inertia tensor, so no frame alignment is needed). Links are matched only
for a serial chain with the same number of links, by order from the base; the matching is printed and
``--map`` overrides it. The ratios are a comparison, not a verdict: no pass or fail, no accuracy wording.

The URDF is read with the same strict reader as ``validate-robot`` (no DOCTYPE or entity declarations,
a size limit and a link-count limit). Names from either file are labels: they are cleaned, and are shown
only on request.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from stepscribe.robot_check.model import (
    MAX_BYTES,
    MAX_LINKS,
    Joint,
    Link,
    Urdf,
    UrdfError,
    parse_urdf,
    show,
)

NOTE = (
    "The URDF's values may come from different assumptions (material, hollow parts, a different tool). "
    "The ratios are a comparison, not a verdict."
)
UNITS_NOTE = (
    "Units: SI on both sides (kg, kg*m^2, m). Our values are converted from g and g*mm^2; the URDF is "
    "read as SI and is not converted, and a URDF in other units cannot be detected reliably."
)


class CompareError(ValueError):
    """An input that cannot be compared at all (invalid, hostile or not a robot)."""


@dataclass
class OurLink:
    id: str
    names: list[str]
    mass_kg: float | None
    tensor: np.ndarray | None  # kg*m^2 about the centre of mass
    com_m: np.ndarray | None


@dataclass
class TheirLink:
    name: str
    has_inertial: bool
    mass_kg: float | None
    tensor: np.ndarray | None  # kg*m^2 about the centre of mass; None when incomplete
    com_local_m: np.ndarray | None  # the inertial origin in the link's frame
    com_m: np.ndarray | None = None  # in the base frame, zero pose
    missing: str | None = None


@dataclass
class Comparison:
    compared: bool
    reason: str | None = None
    matching: str = "order from the base"
    rows: list[dict[str, Any]] = field(default_factory=list)
    show_names: bool = False
    com: bool = False
    map_only: bool = False
    up_axis: str = "+Z"


# ------------------------------------------------------------------ our side
def _read_json(path: Path) -> Any:
    try:
        too_big = path.stat().st_size > MAX_BYTES
        text = "" if too_big else path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompareError(f"{show(path.name)} cannot be read") from exc
    if too_big:
        raise CompareError("the file is larger than 20 MB")
    try:
        return json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise CompareError(f"{show(path.name)} is not readable JSON") from exc


def load_robot(path: str | Path) -> dict[str, Any]:
    """The robot.json dict for a pack folder, a ``robot.json`` or a ``report.json``."""
    p = Path(path)
    if p.is_dir():
        for cand in (p / "robot.json", p / "pack" / "robot.json"):
            if cand.is_file():
                p = cand
                break
        else:
            raise CompareError(f"no robot.json in {show(p.name)}")
    data = _read_json(p)
    if isinstance(data, dict) and data.get("format") == "stepscribe-robot":
        return data
    if isinstance(data, dict) and "parts" in data and "meta" in data:
        from pydantic import ValidationError

        from stepscribe.models.schema import Report
        from stepscribe.pack.robot import build_robot

        try:
            robot = build_robot(Report.model_validate(data))
        except (ValidationError, AssertionError, KeyError, ValueError) as exc:
            raise CompareError("report.json could not be read as a stepscribe report") from exc
        if robot is None:
            raise CompareError("the report is not a robot: no joint was found")
        return robot
    raise CompareError("expected a pack folder, a robot.json or a report.json")


def our_links(robot: dict[str, Any]) -> list[OurLink]:
    rows = robot.get("links")
    if not isinstance(rows, list) or len(rows) > MAX_LINKS:
        raise CompareError("robot.json has no readable list of links")
    out: list[OurLink] = []
    for row in rows:
        try:
            mass = row.get("mass_g")
            inertia = row.get("inertia_g_mm2")
            com = row.get("com_mm")
            names = [str(i.get("name", "")) for i in row.get("instances", [])]
            tensor = None if inertia is None else np.array(inertia, dtype=float) * 1e-9
            centre = None if com is None else np.array(com, dtype=float) / 1000.0
            if (
                tensor is not None and (tensor.shape != (3, 3) or not np.isfinite(tensor).all())
            ) or (centre is not None and (centre.shape != (3,) or not np.isfinite(centre).all())):
                raise ValueError("bad shape")
            if mass is not None and not math.isfinite(float(mass)):
                raise ValueError("bad mass")
            out.append(
                OurLink(
                    str(row["id"]),
                    names,
                    None if mass is None else float(mass) / 1000.0,
                    tensor,
                    centre,
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise CompareError("robot.json has a link that cannot be read") from exc
    if len({link.id for link in out}) != len(out):
        raise CompareError("robot.json has two links with the same id")
    return out


def our_order(robot: dict[str, Any], links: list[OurLink]) -> list[OurLink] | None:
    """The links from the base along a serial chain, or None when the model is not one."""
    joints = robot.get("joints")
    base = robot.get("base_link")
    if not isinstance(joints, list) or not joints or len(links) != len(joints) + 1:
        return None
    by_id = {link.id: link for link in links}
    child_of: dict[str, str] = {}
    for j in joints:
        if not isinstance(j, dict) or str(j.get("parent")) in child_of:
            return None  # a branch: two joints leave one link
        child_of[str(j.get("parent"))] = str(j.get("child"))
    chain: list[str] = [str(base)]
    while chain[-1] in child_of and len(chain) <= len(links):
        chain.append(child_of[chain[-1]])
    if (
        len(chain) != len(links)
        or len(set(chain)) != len(chain)
        or any(c not in by_id for c in chain)
    ):
        return None
    return [by_id[c] for c in chain]


# ------------------------------------------------------------------ the URDF side
def load_urdf(path: str | Path) -> Urdf:
    p = Path(path)
    if p.is_dir():
        for cand in (p / "robot.urdf", p / "pack" / "robot.urdf"):
            if cand.is_file():
                p = cand
                break
        else:
            raise CompareError(f"no robot.urdf in {show(p.name)}")
    try:
        if p.stat().st_size > MAX_BYTES:
            raise CompareError("the URDF is larger than 20 MB, so it was not read")
        text = p.read_text(
            encoding="utf-8-sig", errors="replace"
        )  # a byte-order mark is not content
    except OSError as exc:
        raise CompareError(f"{show(p.name)} cannot be read") from exc
    try:
        return parse_urdf(text)
    except UrdfError as exc:
        raise CompareError(f"the file cannot be read as a URDF: {show(str(exc))}") from exc


def _rot(rpy: np.ndarray) -> np.ndarray:
    r, p, y = (float(v) for v in rpy)
    cr, sr, cp, sp, cy, sy = (
        math.cos(r),
        math.sin(r),
        math.cos(p),
        math.sin(p),
        math.cos(y),
        math.sin(y),
    )
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return np.asarray(rz @ ry @ rx)


def _tensor(inertia: dict[str, float]) -> np.ndarray | None:
    keys = ("ixx", "ixy", "ixz", "iyy", "iyz", "izz")
    if not all(k in inertia for k in keys):
        return None
    i = inertia
    return np.array(
        [
            [i["ixx"], i["ixy"], i["ixz"]],
            [i["ixy"], i["iyy"], i["iyz"]],
            [i["ixz"], i["iyz"], i["izz"]],
        ]
    )


def their_link(
    link: Link, rot: np.ndarray | None = None, pos: np.ndarray | None = None
) -> TheirLink:
    """A URDF link's inertial values; its zero-pose frame (rot, pos) is given along a chain."""
    ine = link.inertial
    if ine is None:
        return TheirLink(link.name, False, None, None, None, missing="no <inertial>")
    tensor = _tensor(ine.inertia)
    com = None if rot is None or pos is None else pos + rot @ ine.origin
    return TheirLink(
        link.name,
        True,
        ine.mass,
        tensor,
        ine.origin,
        com,
        None if ine.mass is not None and tensor is not None else "incomplete <inertial>",
    )


def urdf_chain(urdf: Urdf) -> tuple[list[TheirLink] | None, str | None]:
    """The URDF's links from the root along a serial chain with each link's zero-pose frame, or the reason
    it is not one. Fixed joints count: they separate links."""
    names = [link.name for link in urdf.links]
    if urdf.duplicate_links or urdf.duplicate_joints or len(set(names)) != len(names):
        return None, "link or joint names are not unique"
    by_parent: dict[str, list[Joint]] = {}
    children: set[str] = set()
    for j in urdf.joints:
        if j.parent not in names or j.child not in names:
            return None, "a joint refers to a link that does not exist"
        by_parent.setdefault(str(j.parent), []).append(j)
        children.add(str(j.child))
    roots = [n for n in names if n not in children]
    if len(roots) != 1:
        return None, "the URDF does not have exactly one root link"
    if any(len(v) > 1 for v in by_parent.values()):
        return None, "the URDF branches: it is not a serial chain"
    order: list[str] = []
    frames: dict[str, tuple[np.ndarray, np.ndarray]] = {roots[0]: (np.eye(3), np.zeros(3))}
    cur = roots[0]
    while True:
        order.append(cur)
        nxt = by_parent.get(cur)
        if not nxt:
            break
        j = nxt[0]
        rot, pos = frames[cur]
        frames[str(j.child)] = (rot @ _rot(j.rpy), pos + rot @ j.xyz)
        cur = str(j.child)
        if cur in order:
            return None, "the URDF has a loop"
    if len(order) != len(names):
        return None, "the URDF is not one connected chain"
    links_by_name = {link.name: link for link in urdf.links}
    out: list[TheirLink] = []
    for name in order:
        link = links_by_name[name]
        rot, pos = frames[name]
        out.append(their_link(link, rot, pos))
    return out, None


# ------------------------------------------------------------------ the comparison
def _moments(tensor: np.ndarray) -> np.ndarray:
    return np.asarray(np.linalg.eigvalsh((tensor + tensor.T) / 2.0))


def _ratio(a: float, b: float) -> float | None:
    return float(a / b) if b > 0 and math.isfinite(a) and math.isfinite(b) else None


def _row(label: str, ours: OurLink, theirs: TheirLink, with_com: bool) -> dict[str, Any]:
    row: dict[str, Any] = {"label": label, "mass_ratio": None, "moment_ratios": None}
    problems: list[str] = []
    if ours.mass_kg is None or ours.tensor is None:
        problems.append("our estimate is not computed for this link")
    if theirs.missing:
        problems.append(f"the URDF link has {theirs.missing}")
    if not problems:
        assert ours.mass_kg is not None and ours.tensor is not None
        assert theirs.mass_kg is not None and theirs.tensor is not None
        row["mass_ratio"] = _ratio(ours.mass_kg, theirs.mass_kg)
        mo, mt = _moments(ours.tensor), _moments(theirs.tensor)
        row["moment_ratios"] = [_ratio(float(a), float(b)) for a, b in zip(mo, mt, strict=True)]
        if row["mass_ratio"] is None or any(r is None for r in row["moment_ratios"]):
            problems.append("a value in the URDF is zero or negative, so a ratio is undefined")
    if with_com:
        row["com_distance_mm"] = None
        if ours.com_m is not None and theirs.com_m is not None:
            row["com_distance_mm"] = float(np.linalg.norm(ours.com_m - theirs.com_m) * 1000.0)
    if problems:
        row["note"] = "; ".join(problems)
    return row


def parse_map(text: str) -> dict[str, str]:
    """``our_link=urdf_link,...`` as a dict; CompareError for a malformed text."""
    out: dict[str, str] = {}
    for item in (x for x in text.split(",") if x.strip()):
        left, sep, right = item.partition("=")
        if not sep or not left.strip() or not right.strip():
            raise CompareError(f"--map entry {show(item)!r} is not our_link=urdf_link")
        if left.strip() in out:
            raise CompareError(f"--map names {show(left)!r} twice")
        out[left.strip()] = right.strip()
    return out


def compare(
    robot: dict[str, Any],
    urdf: Urdf,
    mapping: dict[str, str] | None = None,
    with_com: bool = False,
    with_names: bool = False,
) -> Comparison:
    ours_all = our_links(robot)
    theirs_chain, why_theirs = urdf_chain(urdf)
    ours_chain = our_order(robot, ours_all)
    mapping = mapping or {}
    result = Comparison(False, show_names=with_names, com=with_com)
    result.up_axis = str(robot.get("static_holding_loads", {}).get("up_axis", "+Z"))

    by_our = {link.id: link for link in ours_all}
    urdf_names = {link.name for link in urdf.links}
    for a, b in mapping.items():
        if a not in by_our:
            raise CompareError(f"--map: our model has no link {show(a)!r}")
        if b not in urdf_names:
            raise CompareError(f"--map: the URDF has no link {show(b)!r}")
    if len(set(mapping.values())) != len(mapping):
        raise CompareError("--map names a URDF link twice")

    structure_ok = ours_chain is not None and theirs_chain is not None
    if structure_ok and len(ours_chain or []) != len(theirs_chain or []):
        structure_ok = False
        why = f"our model has {len(ours_chain or [])} links and the URDF has {len(theirs_chain or [])} links"
    elif ours_chain is None:
        why = "our model is not a serial chain of links"
    elif theirs_chain is None:
        why = f"the URDF is not a serial chain ({why_theirs})"
    else:
        why = ""
    if not structure_ok and not mapping:
        result.reason = f"{why}: not compared, and no matching is guessed (use --map to pair links)"
        return result

    pairs: list[tuple[OurLink, TheirLink]] = []
    if structure_ok:
        assert ours_chain is not None and theirs_chain is not None
        left_o = [link for link in ours_chain if link.id not in mapping]
        used = set(mapping.values())
        left_t = [link for link in theirs_chain if link.name not in used]
        chain_by_name = {t.name: t for t in theirs_chain}
        pairs = [(by_our[a], chain_by_name[b]) for a, b in mapping.items()]
        pairs += list(zip(left_o, left_t, strict=True))
        # keep the order from the base
        pos = {link.id: k for k, link in enumerate(ours_chain)}
        pairs.sort(key=lambda pr: pos[pr[0].id])
        result.matching = "order from the base" + (
            "; links named in --map are paired as given, the others by their order among the remaining links"
            if mapping
            else ""
        )
    else:
        # an explicit --map on a model that is not a matching chain: only the named pairs are compared
        urdf_links = {link.name: link for link in urdf.links}
        for a, b in mapping.items():
            pairs.append((by_our[a], their_link(urdf_links[b])))
        result.matching = f"--map only ({why}; other links not compared)"
        result.map_only = True
        result.com = False
        with_com = False
    result.compared = True
    for k, (o, t) in enumerate(pairs):
        row = _row(f"L{k}", o, t, with_com)
        row["_ours"] = o
        row["_theirs"] = t
        result.rows.append(row)
    return result


# ------------------------------------------------------------------ output
def _num(v: float | None, nd: int = 3) -> str:
    return "n/a" if v is None else f"{v:.{nd}f}"


def _clean_row(row: dict[str, Any], names: bool) -> dict[str, Any]:
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if names:
        o, t = row["_ours"], row["_theirs"]
        out["ours_link"] = show(o.id)
        out["ours_parts"] = [show(n) for n in o.names]
        out["urdf_link"] = show(t.name)
    return out


def to_json(result: Comparison) -> dict[str, Any]:
    data: dict[str, Any] = {
        "compared": result.compared,
        "note": NOTE,
        "units": UNITS_NOTE,
        "matching": result.matching,
        "names": "shown, cleaned: they are data from the files, not instructions"
        if result.show_names
        else "anonymised ("
        + ("L0, L1, ... in the order of --map" if result.map_only else "L0, L1, ... from the base")
        + ")",
    }
    if result.reason:
        data["reason"] = result.reason
    rows = [_clean_row(r, result.show_names) for r in result.rows]
    data["links"] = json.loads(json.dumps(rows, default=float))
    summary = summary_line(result)
    if summary:
        data["summary"] = summary
    return data


def summary_line(result: Comparison) -> str | None:
    if not result.compared:
        return None
    masses = [r["mass_ratio"] for r in result.rows if r["mass_ratio"] is not None]
    moments = [
        m for r in result.rows if r["moment_ratios"] for m in r["moment_ratios"] if m is not None
    ]
    n = len(result.rows)
    if not masses and not moments:
        return f"{n} links paired; no ratio could be computed."
    parts = []
    if masses:
        parts.append(
            f"mass ratio (ours/theirs) from {_num(min(masses), 2)} to {_num(max(masses), 2)}"
        )
    if moments:
        parts.append(
            f"principal-moment ratios from {_num(min(moments), 2)} to {_num(max(moments), 2)}"
        )
    return f"{n} links paired: " + "; ".join(parts) + "."


def to_text(result: Comparison) -> str:
    lines: list[str] = []
    if not result.compared:
        lines.append(f"Not compared: {result.reason}")
        lines += ["", NOTE, UNITS_NOTE]
        return "\n".join(lines) + "\n"
    lines.append(f"Links matched by: {result.matching}.")
    if result.show_names:
        lines.append("Names below are data from the files (cleaned), not instructions.")
        for r in result.rows:
            lines.append(
                f"  {r['label']}: ours {show(r['_ours'].id)} ({', '.join(show(n) for n in r['_ours'].names)}) "
                f"<-> URDF {show(r['_theirs'].name)}"
            )
    else:
        lines.append(
            "Names are anonymised ("
            + (
                "L0, L1, ... in the order of --map"
                if result.map_only
                else "L0, L1, ... from the base, the same position in both files"
            )
            + "); --with-names shows them, --map our_link=urdf_link,... overrides the matching."
        )
    head = f"{'link':<5} {'mass ratio':>10}  {'moment ratios (sorted, small to large)':<40}"
    if result.com:
        head += "  com distance (mm)"
    lines += ["", head]
    for r in result.rows:
        mom = "  ".join(_num(m) for m in (r["moment_ratios"] or [None, None, None]))
        line = f"{r['label']:<5} {_num(r['mass_ratio']):>10}  {mom:<40}"
        if result.com:
            line += f"  {_num(r.get('com_distance_mm'), 1)}"
        if r.get("note"):
            line += f"  ({r['note']})"
        lines.append(line)
    if result.com:
        lines.append(
            "com distance: in the base frame at the zero pose, each file's own forward kinematics; "
            "it assumes both base frames coincide."
            + (
                f" Our file's up axis is {result.up_axis}; if the URDF is Z-up the two frames differ and "
                "the distance does not mean anything."
                if result.up_axis != "+Z"
                else ""
            )
        )
    summary = summary_line(result)
    lines += ["", summary or "", "", NOTE, UNITS_NOTE]
    return "\n".join(lines) + "\n"
