# Report schema 0.7.0: the one bump

Status: pending (the schema is still 0.6.0)

The report schema is bumped once, to 0.7.0, after the 2.1 pull requests A (#24), B (#25) and C (#27) are in
and this one (#29) is merged. No pull request before that bump changes `SCHEMA_VERSION`. Every change below is
additive: an optional field that is left out of the report when it has no value, or a new value of an existing
label. A report written under 0.6.0 stays valid.

The bump commit must cover every line below and change the status line above to `Status: released in 0.7.0`.
`tests/test_schema_pending.py` fails if the version moves while the status says pending, or the other way round.

## Added by #29 (checked by the test)

- `Hole.thread`: a `ModelledThread` (nominal size, minor and major diameter, faces, evidence), absent unless a
  hole's bores alternate between a minor and a major diameter.
- `ShapeClass.label`: the value `serrated` (equal repeats that fit no gear module or belt pitch).

## Added by #24 and #25 (to check when those are merged)

- `Mass.designer_mass`: a `DesignerMass` (given, used, estimated, note, ratio note), absent unless the designer
  gave a mass for the part (#24).
- `Mass.material_source`: the value `designer_mass` (#24).
- `Mass.density_range`: a `DensityRange` (minimum, maximum, reason), present where the density is an assumption (#25).
