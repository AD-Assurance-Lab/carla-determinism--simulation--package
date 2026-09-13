# Health check and guard options, 2026-09-13

Written after a read of the package, its tests, and the four study repositories on
this machine that use it. Sections 1 to 4 record what was found and what was
recommended, as written before any change.

**Status, later the same day.** Steps 1 to 3 of section 4 are done in this repository,
as three tagged releases: v1.1.0 (version string, exact port match, pytest scope),
v1.2.0 (`pin_torch`, `check_torch`, `provenance`), v1.3.0 (launcher, D-4 and D-6
checks, audit with pre-commit hook, Claude Code hook). The consumer-side work in step 1
(the steering pin, `require_measurable` in its sync-mode helper, the verifier-scaling
reinstall) and the per-repository hook installation in step 4 are not done here. The
D-7 amendment request stays open; the AEB study is being rebuilt by its researcher, and
no action is needed on it now.

## 1. Is the package running correctly?

**The code is sound. The release around it is not.**

| check | result |
|---|---|
| lock digest against the shipped `RULES.md` | intact |
| tests in a venv that has the package installed | 17 of 17 pass |
| tests under the system `python3` | 16 of 17 pass, and the 16 pass by accident (see 1.1) |
| `__version__` in `__init__.py` | 1.0.0 |
| `version` in `pyproject.toml` | 1.1.0 |
| tag `v1.1.0` on origin | missing (only `v1.0.0` exists) |
| origin `main` against local `main` | same commit |

### 1.1 Defects, most important first

**The version string is wrong (release).** `__init__.py` says 1.0.0 and `pyproject.toml`
says 1.1.0. `CLAUDE.md` says to change them together. The multi-condition study noticed
this on 2026-09-12 and wrote "reported to Zach" in its pending file. Every provenance
block that records `cd.__version__` now records the wrong number.

**Tag `v1.1.0` does not exist (release).** The multi-condition bootstrap installs
`git+...@v1.1.0` when the local checkout is absent. That path fails on any other machine.

**The steering study, the reference implementation, pins `v1.0.0` (consumer).** That
release has no `hygiene` module. Its `carla_env.py` calls `server_age_s` by hand to skip
a reload, but it never calls `require_fresh_server` or `require_clean_world`. So the
stale-server refusal and the leaked-actor refusal are not in force in the one repo the
others copy from.

**The verifier-scaling venv holds a snapshot copy, not an editable install (consumer).**
Its `direct_url.json` is a `file://` install without the editable flag. It will drift
from the checkout silently, which is the failure mode the package exists to prevent.

**The test run under system Python passes by accident (D-9 class).** `PYTHONPATH` carries
the ROS Jazzy site-packages. Its `launch_testing` pytest plugin imports every `.py` file
pytest walks, including `src/carla_determinism/__init__.py`, and that import puts `src/`
on `sys.path`. The tests then import the package from there. Without the ROS path, or
with the plugin off, collection fails with "No module named carla_determinism". A green
run that proves nothing is exactly what D-9 forbids.

**Port match is by substring (code).** `server_cmdline` and `server_age_s` test
`f"-carla-rpc-port={port}" in arg`. A request for port 300 matches a server on 3000.
Low risk with the lab's ports, but a wrong-server match is the worst kind of wrong.

**Two frozen rules have no check (code).** D-4 (post-process on, exposure manual) lives on
the camera blueprint and is never asserted. D-6 (one client per port) is never asserted.
Both are checkable: D-4 at camera spawn, D-6 by counting established connections to the
port in `/proc/net/tcp`.

**One escape hatch exists in a consumer.** Steering's `enable_sync_mode` skips the
preflight when `CARLA_SKIP_PREFLIGHT` is set. The package forbids escape hatches in
itself. A consumer with one gives the same result.

Cosmetic: the CLI test runs `-m carla_determinism.preflight`, the exact form
`__main__.py` says to avoid. The `build/` directory is a stale copy, ignored by git.

### 1.2 Who uses the package, and how

| repository | package | how it is used |
|---|---|---|
| steering | v1.0.0 from git | bind, apply_control, require_deterministic in `enable_sync_mode`; the launcher runs the CLI |
| multi-condition | editable, local main | calls the steering launcher by path; driver refuses if deterministic control is off |
| verifier-scaling | snapshot of local main | copy of the steering harness |
| localized-failure | referenced in `_paths.py` | records provenance |
| verifier-operations | not installed, no `carla` | none |
| log-match-carla-scenarios | not installed | 8 raw `actor.apply_control` calls on lead, cutter and pedestrian actors |

The last row matters only if that repository produces a number. If it does, D-2 applies
to the non-ego actors too. A late command to the lead vehicle moves the scenario.

## 2. CUDA and model determinism, as found

**Training.** `train.py` seeds torch, numpy and random. It does not pin cuDNN or cuBLAS.
`distill.py` pins them only when `DISTILL_DETERMINISTIC=1`, off by default. The study
measured that seed-only training leaves a 1.39x spread across three draws of one seed.

**Inference.** `evaluate.py`, `closed_loop_ledger.py` and `student.py` set nothing. cuDNN
autotuning is off by default, so most convolutions repeat, but nothing asserts it and
`use_deterministic_algorithms` is off. The policy in the loop is not proven to give the
same output for the same frame. The open-loop probe in D-8 records "output computed but
not applied", which is the right instrument for this. It has not been pointed at it.

**Provenance.** No artifact records GPU model, driver or torch version. The steering
notes record that the RTX 5090 migration flipped one marginal cell out of eight.

## 3. Options for guards

The question was how to make sure CARLA always runs under the rules. There are six ways.
They catch different mistakes, so the answer is several of them, not one.

**A. Runtime guard at the choke point.** This exists: `require_deterministic` and
`require_measurable` inside the one function that enables synchronous mode. A new driver
cannot skip it. This is the strongest guard because it reads the live server. Its gaps
are the escape hatch and the two unchecked rules in 1.1.

**B. The launcher lives in the package.** Today the steering repo owns the launcher, and
multi-condition calls it by an absolute path into the steering checkout. Move it to
`python3 -m carla_determinism launch --port N --map Town04`. Then every repository calls
one launcher, the flags cannot go missing, and the package version pins the launcher too.

**C. A provenance stamp.** `cd.provenance(port)` returns one dict: package version, rules
digest, lock state, server argv, server age, deterministic-control flag, torch version,
CUDA version, driver, GPU name. Every artifact carries it. This makes D-11 enforceable
after the fact. Steering has a private version of this; it belongs in the package.

**D. A static audit, run by a git pre-commit hook and by CI.** `python3 -m
carla_determinism audit .` fails a repository that has a raw `vehicle.apply_control(`
outside its choke point, a `CarlaUE4.sh` call outside the launcher, an unpinned or
missing dependency on the package, or a `CARLA_SKIP_PREFLIGHT`. It runs in a second and
needs no simulator. Steering has CI. The other repositories have no hooks and no CI.

**E. A Claude Code hook.** Most of this code is written in Claude Code sessions. A
user-level PreToolUse hook on Bash can refuse any command that contains `CarlaUE4.sh`
or `CarlaUE4-Linux-Shipping` unless it goes through the launcher. Exit code 2 blocks the
call and shows the reason. One hook in `~/.claude/settings.json` covers every repository
at once. The `update-config` skill sets this up.

**F. An OS-level shim.** Rename the real `CarlaUE4.sh` and put a wrapper in its place that
always appends the flags. Not recommended. It hides the mechanism, so the preflight can
no longer tell a correct launch from a rescued one, and it breaks on the next CARLA
upgrade.

**G. A torch module in the package, same pattern as the rest.**
`cd.require_deterministic_torch(seed)` sets `CUBLAS_WORKSPACE_CONFIG` before the first
cuBLAS handle, seeds python, numpy and torch, sets `cudnn.deterministic`, clears
`cudnn.benchmark`, and calls `use_deterministic_algorithms(True)`. `cd.check_torch()`
raises when deterministic algorithms are off, for the inference path. Import torch
inside the function, as the package does with `carla`. Tests must show it can fail.

## 4. Recommendation

Do these in order. Each step is a small commit.

1. **Fix the release today.** Set `__version__` to 1.1.0. Tag `v1.1.0` and push the tag.
   Move the steering pin to `v1.1.0` and call `require_measurable` from its
   `enable_sync_mode`. Reinstall verifier-scaling as editable. Fix the port match. Add
   `[tool.pytest.ini_options] testpaths = ["tests"]` so the suite never walks `src/`, and
   say in the README that tests run after `pip install -e .`.
2. **v1.2.0: C and G.** Provenance and the torch module. Both apply the package's own
   pattern to the two things it does not yet cover.
3. **v1.3.0: B.** Move the launcher into the package. Switch multi-condition and
   verifier-scaling to it. Add the D-4 and D-6 checks to the preflight at the same time.
4. **Guards: D, then E.** The audit command and a pre-commit hook in each repository
   first. The Claude Code hook second. D catches drift at commit time. E catches a hand
   launch during a session. Neither replaces A.
5. **Do not do F.**

Separate from all of this: the D-7 amendment request from the AEB study is open, and
the CLI still prints the ten-repetition floor on every launch. That decision is yours.
Nothing above depends on it.
