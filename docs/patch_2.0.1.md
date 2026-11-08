# Items for a 2.0.1 patch release

A list of what may go into a 2.0.1, kept here so nothing is lost. Nothing on it is released on its own: 2.0.1 is
cut only when the maintainer says so, and not for a single item that changes no behaviour.

- **Repository URL.** Every public link moves from `idris900323/stepscribe-cad` to `idris-botics/stepscribe-cad`
  (README links, demo video and GIF, the `/plugin marketplace add` line, `pyproject.toml` `Repository`, the plugin
  manifest `homepage` and `repository`, and the two tests that assert the URLs). The old URLs redirect, so nothing
  is broken until then; the package metadata on PyPI keeps the old link until a release carries this change.
  Not in that change: `.github/workflows/cla.yml` (its document URL and allowlist are changed separately).
