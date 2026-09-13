# carla-determinism

A pip-installable package. It carries the lab's CARLA determinism rules and the
preflight that enforces them. Every repository that drives CARLA uses it.

`src/carla_determinism/RULES.md` is the content. Read it before you change
anything here. `RULES.lock` hash-locks it.

## Rules for this repository

**Do not edit the frozen part of `RULES.md` without the amendment procedure** in
its section 4. State the measurement that contradicts the rule. Record it in the
study's findings file. Change the rule. Regenerate the lock in the same commit.
`pytest` fails if you do not. That is deliberate.

**Never make the preflight lenient to unblock a run.** Its value is that it
refuses. If a check is wrong, fix the check or amend the rule. Do not add an
escape hatch.

**Do not import any study's config.** The fixed timestep, the port and the
deterministic-control switch are parameters. Studies use different timesteps, so
a package that reads one study's config cannot be shared.

**Do not depend on `carla`.** It ships with each CARLA release, and each study
pins its own. Import it inside the function that needs it. The lock check and the
preflight then work without it.

**Tests must show that a check can fail.** A probe that could not fail once
reported the opposite of the truth, and the lab believed it for a day (D-9).

**Run the tests from a venv that has the package installed.** The system `python3`
carries ROS on `PYTHONPATH`, and a ROS pytest plugin once imported the package from
the checkout, so the suite went green with nothing installed.

**Modules.** `preflight` checks a live server. `hygiene` checks which server. `control`
routes the vehicle command. `cuda` pins and checks torch. `provenance` records the
harness. `launcher` starts the server with the flags. `audit` checks a repository's
code. `cli` wires the commands. Import `carla` and `torch` inside the function that
needs them.

## To release

Change `__version__` in `__init__.py` and `version` in `pyproject.toml` together.
Tag `vX.Y.Z`. Then update the pin in each consuming repository's
`requirements.txt` on purpose. Consumers pin an exact tag, so a rule change
cannot arrive silently in the middle of a study.
