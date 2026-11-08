# Roadmap note: hobby robot models (design only, no code yet)

Four gaps that a hobby quadruped model (many small printed parts, hobby servos, linkages) showed. None of
them is built; this note records the problem, the evidence a fix would need and what stays out of scope.

## 1. Pin-in-clearance-hole revolute joints, and closed-loop degrees of freedom

**Problem.** A model whose joints are small pins in clearance holes (servo horns, linkage pins) gets one or
no joint, because the pivot rule needs a coaxial hole stack of at least 20 mm. Lowering that minimum finds
nothing on the dog model: its pins are not modelled as stacks the rule can see, so a smaller threshold alone
is not the fix. The headline now says how many groups have no joint evidence; it cannot yet find the joints.

**Evidence a detector would need.**
- A cylinder (a pin or screw shank) lying inside a hole of the same axis in a different rigid group, with a
  radial clearance of a few tenths of a millimetre and an overlap length of at least the pin diameter. This is
  already how one joint (KJ1: INS009 turning in the bore of INS010, clearance 0.10 mm) was found.
- A servo horn seated on a spline or a D-shaft: a toothed bore matching a toothed shaft is a fixed
  connection to the output, so the horn's group moves with the servo's output group.
- Coaxial pairs of holes across two groups with a pin through both: a hinge candidate with low confidence
  until a second kind of evidence agrees (a second pin, a servo, a limit).

**Closed loops.** A four-bar leg has more joints than degrees of freedom. The degrees of freedom of a loop need
the Grübler count over the whole joint graph, which is only meaningful when every joint is found. Until the
joint finder is trusted, closed-loop counts should be shown as an upper bound with the number of joints used.

**Out of scope.** Motion limits, singularities and any statement about which joints are driven.

## 2. Components that are not in the STEP file

**Problem.** Electronics, batteries, wires and bought servos are often missing from the CAD file, so the total
mass and the centre of mass are low and the static load numbers are too.

**Shape of a solution.** A `components:` list in `design_context.yaml`: a name, a mass in grams, a position in
the file's axes (or "on part PRT012 at an offset") and an optional box size for the tipping check. They enter
the mass, centre of mass and tipping as point or box masses, are labelled "added by the designer" everywhere
they appear and never become parts of the geometry. A mass the designer gives is used as given.

## 3. Memory per worker

**Problem.** The part pool is sized from free memory and the largest part. A model of many small parts has
very different per-worker memory from a model of a few big ones, and the sizing rule treats them alike.

**Shape of a solution.** Measure the peak memory of a worker for the parts it has done (face count and
memory are recorded per part in the timings), keep a per-model estimate, and let the pool size follow it.
Show the number used and the reason, as the pool line does now. No change to what is analysed.

## 4. Infill and printed weight for FDM parts

**Problem.** A printed part with infill is lighter than the solid the CAD describes, so the mass and the
inertia of a printed model are overestimates. The solid value is what the pack gives today.

**Shape of a solution.** An optional `infill:` percentage (and wall count) in `design_context.yaml`, per part
or for all parts, applied only to parts whose process is declared FDM. The effective density is the solid
density times a shell-plus-infill fraction. The pack says the number is an estimate from the stated infill,
and a mass the designer measured replaces it. Until the designer gives it, the text keeps saying that a
printed part with infill is lighter than the estimate.
