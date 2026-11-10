# Report schema 0.7.0: the one bump

Status: released in 0.7.0

The report schema was bumped once, to 0.7.0, in the 2.1.0 release, after the 2.1 pull requests A (#24), B (#25),
C (#27) and the output-quality fixes (#29) were in. No pull request before that bump changed `SCHEMA_VERSION`. Every change below is
additive: an optional field that is left out of the report when it has no value, or a new value of an existing
label. A report written under 0.6.0 stays valid.

The bump covers every line below. `tests/test_schema_pending.py` fails if the version and the status line above
disagree.

## Added by #29 (checked by the test)

- `Hole.thread`: a `ModelledThread` (nominal size, minor and major diameter, faces, evidence), absent unless a
  hole's bores alternate between a minor and a major diameter.
- `ShapeClass.label`: the value `serrated` (equal repeats that fit no gear module or belt pitch).

## Added by #24 and #25 (merged; checked by the test)

- `MassProperties.designer_mass`: a `DesignerMass` (given, used, estimated, note, ratio note), absent unless the designer
  gave a mass for the part (#24).
- `MassProperties.material_source`: the value `designer_mass` (#24).
- `MassProperties.density_range`: a `DensityRange` (minimum, maximum, reason), present where the density is an assumption (#25).
