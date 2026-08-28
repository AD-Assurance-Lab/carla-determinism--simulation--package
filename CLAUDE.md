# CLAUDE.md — carla-determinism

A pip-installable package carrying the lab's CARLA determinism rules and the preflight
that enforces them. Consumed by every repo that drives CARLA.

**`src/carla_determinism/RULES.md` is the content.** Read it before changing anything
here. It is hash-locked by `RULES.lock`.

## Rules for working in this repo

- **Do not edit the frozen section of `RULES.md` without the amendment procedure**
  (its section 4): state the contradicting measurement, record it in the study's findings
  file, change the rule, regenerate the lock in the SAME commit. `pytest` fails otherwise,
  which is deliberate.
- **Never make the preflight lenient to unblock a run.** The whole value is that it
  refuses. If it is wrong, fix the check or amend the rule; do not add an escape hatch.
- **This package must not import any study's config.** Study-specific values
  (`fixed_dt`, port, whether deterministic control is on) are parameters. A package that
  reaches into one study's config cannot be shared by studies whose timesteps differ.
- **`carla` is not a dependency** and must stay that way — it ships per CARLA release and
  each study pins its own. Import it lazily, inside the function that needs it, so the
  lock check and the /proc preflight work without it installed.
- Tests must prove the checks can FAIL, not just pass. Rule D-9 exists because a probe
  that could not fail reported the opposite of the truth and was believed for a day.

## Releasing

Bump `__version__` in `__init__.py` and `version` in `pyproject.toml` together, tag
`vX.Y.Z`, and update the pin in each consuming repo's `requirements.txt` deliberately —
consumers pin an exact tag so a rule change can never arrive silently mid-study.
