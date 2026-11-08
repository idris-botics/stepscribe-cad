# Mass distribution and static joint loads

`05_understanding.md` (section "Mass distribution and static load (estimates)") and `robot.json` carry
estimates from CAD volume and the material or density named for each part. They are not measured values.

## What is computed

- Principal moments, principal axes and radii of gyration about the centre of mass, for every part, every
  link (robots) and the assembly. Only for a valid closed solid with a known material or density; otherwise
  the line says `not computed: <reason>`.
- For a robot: the **static holding torque** (a force for a prismatic joint) of each joint at the pose stored
  in the file, **gravity only**, from the link masses and centres of mass. Label: *static holding torque,
  gravity only, at this pose; not dynamic, not a motor selection*. The value is what the joint must supply to
  hold the pose (minus what gravity applies about the joint's positive axis). A joint is refused when a link
  beyond it has an unknown mass, geometry that is complex or free-form, or is not a closed solid.

## Optional payload

```yaml
payload:
  mass_kg: 2.5
  offset_mm: [0, 0, 150]   # from the last joint's axis point, in the file's axes
```

## A mass you measured

```yaml
parts:
  TopPlate:            # the part name as shown in the pack, the same key as `material:`
    mass_g: 412.5      # grams
```

The key is `mass_g`, under the part's name in `parts:` (like `material:` and `process:`).

- For a **closed valid solid** the mass is replaced by yours and the inertia is scaled by your mass over the
  estimated mass (without a material or density the estimate is the one a uniform density of mass over
  volume gives). The centre of mass and the principal axes do not change. The pack section, `robot.json`
  (`mass_label`, `mass_from_designer_parts` on the link) and the URDF header comments label it
  *mass from designer; inertia assumes the same distribution as the estimate*. `report.json` carries
  `mass.designer_mass` for such a part, and only for such a part.
- When the mass you give is below 50 % or above 120 % of the solid estimate (from the material or density) one
  neutral note is printed beside the part: "the measured mass is N% of the solid estimate; the part may be
  hollow, printed or made of a different material". It is in the pack section, the part text and `report.json`
  (`mass.designer_mass.ratio_note`). The given mass is used either way.
- A part that is **refused** (not a closed solid, a shell or surface, complex or free-form geometry) keeps
  its refusal. The mass you gave is not used, and the pack, `robot.json` and `report.json` say so and why.
- A value that is not a number, is not above 0, or is not finite stops the run with a message that names
  the part. A name that matches no part is reported as a warning.

## Agreement between two methods on generated shapes

`scripts/check_inertia.py` (and `tests/test_inertia_agreement.py`) generate deterministic solids from a seeded
generator (boxes, cylinders, spheres, and boxes and cylinders with cut holes, each rotated and offset at
random) and compare, for each, the mass, the centre of mass and the three principal moments from

1. the value stepscribe reports (OpenCASCADE's exact integration over the B-rep), and
2. an independent integral of a fine tessellation of the same solid: signed tetrahedra over the closed
   triangle mesh, in numpy only. OpenCASCADE only makes the triangles for this one.

This shows that the two methods agree on these shapes. It says nothing about real parts, which are not
uniform solids, and it is not a statement of accuracy. A fast subset (one of each kind) runs in the normal
test suite; the full set of 300 is marked slow and runs in CI. Run it yourself with
`python scripts/check_inertia.py --count 300`.

**Tolerance**: 1e-3 relative on the mass and on each principal moment, and 1e-4 of the part's diagonal on the
centre of mass. A mesh is inscribed in every curved surface, so it is slightly smaller than the solid; for a
chord that subtends an angle t the area of a circle is short by about t^2/6 and a moment of it by at most about
4 t^2/6. The meshes use t <= 0.03 rad, which bounds the difference from the tessellation by 6e-4, so 1e-3 is
above what the mesh itself can cause. A larger difference points at one of the two methods.

## Ranges where the assumption is shaky

A range is shown only where there is a documented reason:

- the density was **guessed from a part name** ("density guessed from the name; range for the family"), or
- the material is known **only at family level**, a keyword with no grade such as `steel` or `aluminium`
  ("material known only at family level; range for the family").

The typical density range of each family is in `stepscribe/knowledge/material_density_ranges.yaml`, with the
general reference class it stands for (as `source` and as a comment above each entry). **Any digit in a material
text counts as a grade**: `aluminium 6061`, `alu6061` and `304 stainless` have no range, `aluminium` has one. A
material with a grade, a density you state
(`--density`), a density read from the STEP file and a measured mass (`mass_g`) have **no** range.

No lower bound is invented for a part that might be hollow or cast; the assumptions carry one fixed sentence
instead: *If a part is hollow or cast, its real mass is lower than the estimate.*

- For the printed-plastic families (`pla`, `petg`, `abs`, `nylon`) the range text adds "solid value; a printed
  part with infill is lighter". For `cf` it adds "the range covers both a carbon laminate and carbon-filled
  filament".
- The point value stays the nominal one; `robot.json` and `robot.urdf` keep using it. A range appears beside
  it: `density_range` on a part's `mass` in `report.json`; `mass_range` (min, max, reason) and
  `principal_inertia.range` on a link in `robot.json`; `value_range` (min, max, reason) on a joint load. The URDF
  header says that ranges exist.
- The pack section lines read "low to high (reason): mass, principal moments, radii of gyration". For one
  part the radius of gyration does not depend on a uniform density, so it reads as one value.
- A link or the assembly takes the range over the corners of its parts' density ranges (each uncertain part at
  its low or high density; the instances of one part move together). With more than ten uncertain parts the
  corners are replaced by all-low, all-high and every single flip, and the link or assembly range is labelled
  **"approximate range"** in the pack and in `robot.json` (`mass_range.label`, `principal_inertia.range.label`).
  The exact extremes of the moments can then lie slightly outside it. (The static holding torque range is exact
  interval arithmetic and is never labelled approximate.)
- **Static holding torque** uses interval arithmetic: each part's term is linear in its mass and may have
  either sign (a counterweight), so each term takes its own min and max, never "all low" or "all high". A joint
  that is "not computed" stays so.

## Which way gravity points

Gravity points along the opposite of the up axis used for the analysis. The up axis is `+Z` unless you pass
`--up` (for example `--up +Y`) on the command line or set the **Up axis** field of the UI. The designer file
`design_context.yaml` cannot set the up axis: it is an analysis option, not design intent, and it also decides
the front, top and side views, the tipping check and the load paths. The pack section and `robot.json`
(`gravity_direction`, `gravity_note`) state the axis that was used.

## Not included

Support reactions, fastener load share, motor or gearbox sizing and any safety statement.
