# Compare with an existing URDF (`stepscribe compare-robot`)

```
stepscribe compare-robot <pack folder | report.json | robot.json> <existing.urdf> [--com] [--map a=b,...] [--with-names] [--json]
```

> The URDF's values may come from different assumptions (material, hollow parts, a different tool). The ratios
> are a comparison, not a verdict.

The command is printed with that note every time. It gives no pass or fail.

## What it compares

Per link, our estimates against the URDF's `<inertial>` values:

- the **mass ratio** (ours / theirs), and
- the ratios of the **sorted principal moments** about the centre of mass: the eigenvalues of each inertia
  tensor, smallest first. The eigenvalues do not depend on the frame a tensor is written in, so no frame
  alignment is needed.

`--com` also prints the distance between the two centres of mass in the base frame at the zero pose, from each
file's own forward kinematics. It only means something when both files put the base frame at the same place.

Units are SI on both sides (kg, kg\*m^2, m). Our values are converted from g and g\*mm^2. The URDF is read as SI
and is not converted: a URDF in other units cannot be detected reliably, so the units are stated rather than
checked.

## How links are matched

Only for a **serial chain with the same number of links**: by order from the base. The matching is printed. If
the counts differ, or either side is not a chain (a branch, a loop, several roots), the command says so and
stops without guessing; the exit code is still 0. `--map our_link=urdf_link,...` pairs links yourself: the
named pairs are compared, and the rest are matched by order when the structure allows it.

A link with no `<inertial>` in the URDF, an incomplete one, or a link we have no estimate for (for example
because no material was given) is reported as such, with no ratio.

## Names and sharing

Link names are **anonymised by default** (`L0`, `L1`, ... from the base; the same position in both files), so the
output can be shared without sharing the files or the names in them. `--with-names` adds the files' names,
cleaned, and labelled as data from the files. `--json` gives the same content as data: no absolute masses or
inertias, only ratios.

To share a comparison: run it without `--with-names` and send the table or the `--json` text. The ratios say
nothing about the URDF beyond how it relates to our estimates.

## Safe reading

The URDF is read with the reader `validate-robot` uses: no DOCTYPE or entity declarations, at most 20 MB and at
most 5000 links or joints. A file that breaks a rule, or is not well-formed, is refused with a plain message and
exit code 1; so is an input that is not a robot. Names from either file are labels and are never treated as
instructions.
