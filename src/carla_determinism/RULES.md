# CARLA determinism rules — AD Assurance Lab

**Not a standard.** The lab works to actual standards (ISO 26262, ISO 21448, FMVSS) and
this is not one of them. It is a set of measured operating rules for our own simulator,
carrying the same weight as an internal lab procedure and no more.

**Scope:** every study, every repo, every person, wherever CARLA produces a number.

**Origin:** measured in `formal-verification--steering--code` on 2026-08-28, on the
Town06 branch, after a competence gate reported "held 2/3" for a checkpoint that had not
changed between runs.

This file is hash-locked. `RULES.lock` holds a SHA-256 over the frozen section below, and
`carla_determinism.require_deterministic()` refuses to certify a simulator whose rules
have been edited without going through the amendment procedure in §4. Editing a rule to
make a run pass is the failure this exists to prevent.

---

## 1. What was actually wrong, in one paragraph

Synchronous mode with a fixed timestep synchronises **the tick**, not the **command queue
feeding it**. `vehicle.apply_control()` is a fire-and-forget RPC: it returns as soon as
the message is written, and whether the server has registered it before it processes
`world.tick()` is a wall-clock race. The race is invisible while a command is unchanged —
a late arrival re-applies the same value — so it only bites on a step where the command
*changes*, which in a closed-loop run is every step. Measured open loop, with the feedback
cut and the command sequence a pure function of the step index, three repetitions of one
scripted run ended up **60 m apart**. Nothing in the result reveals it: both trajectories
are physically plausible, and every determinism setting the study had pinned was pinned
correctly.

---

## 2. Frozen rules

Every rule below is a measurement, not a preference. The bracketed figure is what
violating it cost when it was measured.

**D-1. Synchronous mode, fixed timestep, substepping that covers the whole step.**
`fixed_delta_seconds <= max_substep_delta_time * max_substeps`, or physics silently
advances less than the full step and the vehicle covers less ground than its reported
velocity implies.

**D-2. Never issue a vehicle command with a fire-and-forget RPC.** Use an acknowledged
batch command — `client.apply_batch_sync([carla.command.ApplyVehicleControl(...)],
False)` — so the command is provably registered before the tick that consumes it.
[`apply_control()`: physics diverges the first time a command changes; up to 60 m over
200 steps. `apply_batch_sync`: pose, velocity, gear and applied-control readback
bit-identical for every step of every rep.]

**D-3. Launch the server with `-notexturestreaming`.** UE4 streams texture mips in
asynchronously, so which mip is resident when a frame renders depends on load timing
rather than on world state. [Dominant render entropy source: injected steering noise
3.9e-3 -> 2.4e-5, a 168x reduction, and it removes the cold-server first-run outlier
that otherwise makes run 1 of every session disagree with runs 2..N.]

**D-4. Keep `enable_postprocess_effects` TRUE and pin exposure manually.** Manual
exposure lives *inside* the postprocess chain, so disabling postprocessing silently
un-pins it. [postprocess off: injected steering noise rose to 4.8e-2, the worst of any
configuration tested — roughly 2000x worse than leaving it on.]

**D-5. `-quality-level=Epic`.** Not a visual preference — a determinism result.
[High: 5.2e-1, catastrophically worse than Epic's 2.4e-5.]

**D-6. One client per port, and restart the server before every measurement run.** In
synchronous mode any connected client's `tick()` advances the world, so two processes
ticking one server corrupt each other while both appear to work. A long-lived server also
degrades silently: it keeps answering and keeps reporting plausible velocities while it
stops advancing physics correctly.

**D-7. Bit-exact closed-loop replay is NOT achievable, and no configuration reaches it.**
On a scene where nothing moves at all — vehicle held on the brake, zero displacement to
full float precision, camera rigid, weather fixed, exposure manual — frames at the same
index across repetitions are never bit-identical. The floor is ~30 pixels of 307,200
differing by at most 13 levels, and a longer settle does not converge it away, so it is
generated per frame rather than inherited. **Therefore every closed-loop number remains a
RATE over at least 10 repetitions with a confidence interval.** D-1..D-6 shrink the noise;
they do not remove it, and no future version of this file may claim they do without a
measurement showing a frozen scene rendering bit-identically across reps.

**D-8. Measure determinism OPEN LOOP, never closed loop.** A closed-loop probe measures
physics, rendering and feedback amplification at once, so every candidate cause produces
the same symptom and none can be distinguished. Cut the feedback: drive a command
sequence that is a pure function of the step index, and record pose, a hash of the raw
sensor buffer, and the model's output *computed but not applied*. Those three streams
separate physics from rendering from amplification.

**D-9. A determinism probe must be able to fail.** Check subprocess return codes, and
confirm each repetition actually rewrote its artifact before comparing — results files
are usually overwritten in place, so a crashed repetition leaves the previous one on disk
and the probe compares a file with itself and reports IDENTICAL. Copy each repetition's
output to its own path before the next one runs. [This defect produced a false "runs are
reproducible" result that contradicted the true measurement and cost a day.]

**D-10. Amplification is a property of the POLICY, not the simulator.** With physics
bit-exact and only the render floor left, a 2.6e-6 steering perturbation grew to 7.6 ft of
cross-track error over 349 steps. A contractive, competent policy suppresses that
perturbation; a marginal one amplifies it. So run-to-run spread is a *measurement of
closed-loop stability margin*, and a policy whose verdict flips between repetitions is
reporting its own marginality. Do not "fix" that spread by adding repetitions until the
verdict settles.

**D-11. Data captured under a violating harness is not reusable.** Training images
captured with texture streaming on contain mip variation that a `-notexturestreaming`
evaluation will never show, which is a train/test distribution shift. Trajectories driven
through a racing command path sample a different state distribution than the corrected
harness produces. Recollect; do not reweight, filter or reuse.

---

## 3. Preflight

`carla_determinism.require_deterministic(world, ...)` asserts D-1 through D-6 against a
live server and against this file's own hash, and is called by every entry point that
produces a measurement. It reads the server's actual command line from `/proc`, because
D-3 and D-5 are launch flags and are invisible over the Python API — a server someone
started by hand looks completely normal over RPC and quietly produces noisier results.

    python3 -m carla_determinism                      # verify, exit 1 on violation
    python3 -m carla_determinism --write              # regenerate the lock (§4 only)

## 4. Amendment procedure

A rule changes only by: stating what measurement contradicts it, recording that
measurement in the study's findings file, changing the rule, regenerating the lock in the
same commit, and naming the amendment here. A rule may not be relaxed because a run is
inconvenient. Amendments so far: none.

---

## 5. Session hygiene (NOT part of the frozen section)

Deliberately outside §2 and outside the lock. §2 is about how a server must be
*configured*; these are about *which* server you are measuring on, and they are
enforced in code (`carla_determinism.hygiene`) rather than frozen as rules. Adding
them to §2 would need the §4 amendment procedure and Zach's request; this section
does not, because it changes no frozen rule.

**Why they exist.** Both were prose in each repo, re-typed into each new driver, and
both drifted the moment a driver was added. Measured in
`formal-verification--steering--code` on 2026-08-30:

* one capture driver restarted before every capture; its sibling restarted **not at
  all** and took all 24 verification captures behind a deployment-test certificate in
  a single server session;
* a killed capture left its vehicle and camera alive -- SIGTERM does not run Python
  cleanup -- and the next capture rendered a road with a parked car on it.

Neither is visible downstream. The arrays are the right shape and full of plausible
frames.

    cd.require_measurable(port, world)   # fresh server + empty world + clean exit

`require_fresh_server` refuses a server older than an hour (it leaks ~10.5 GiB over
11 h, and a degraded one keeps answering while physics stops advancing).
`require_clean_world` refuses a world that already holds actors.
`install_cleanup_handlers` makes SIGTERM unwind so `finally` blocks run.

**Call it from the choke point every measurement passes through** -- whatever enables
synchronous mode or spawns the vehicle -- never from each driver script. A rule
enforced by copying is a rule that drifts; that is the whole lesson of this section.

---

## 6. Model determinism and provenance (NOT part of the frozen section)

Outside §2 and outside the lock, for the same reason as §5: nothing here changes a
frozen rule. §2 is about the simulator. This is about the model in the loop, and about
the record that says which harness produced a number.

**Why it exists.** A seed is not enough. Measured in `formal-verification--steering--code`
(`docs/E2_FINDINGS.md`): three draws of "seed 0" on the same data and the same
objective gave fog p99 |err| of 0.1027, 0.1427 and 0.1036, a 1.39x spread, as large as
the spread across six different seeds. cuDNN picks kernels by autotuning, several
backward kernels reduce in a data-dependent order, and cuBLAS is repeatable only when
`CUBLAS_WORKSPACE_CONFIG` is set before its first handle exists. Inference had none of
these pinned, so the policy in the loop was not shown to give the same output for the
same frame.

    cd.pin_torch(seed=0)      # configure, before the first CUDA call in the process
    cd.require_torch()        # assert, before a measurement that runs a model

`pin_torch` refuses when CUDA is already initialised and the cuBLAS variable is unset,
because a pin that silently does nothing is worse than none. `check_torch` reports
M-1 (deterministic algorithms off), M-2 (`cudnn.benchmark` on), M-3
(`cudnn.deterministic` off) and M-4 (cuBLAS variable unset with CUDA present). A
missing torch is reported, never passed.

**Provenance.** D-11 is enforceable only if an artifact says which harness produced it.

    stamp = cd.provenance(port, world, deterministic_control=True)

returns the package version, the rules digest, the lock state, the server's real
command line and age, the D-1 world settings, and the torch, CUDA, cuDNN, driver and
GPU versions with the pin state. Unknown is recorded as None, never as False. Write it
into every artifact. The steering notes record that a GPU migration flipped one
marginal cell of eight; without this record that cannot be seen afterwards.

---

## 7. Launcher, audit and hooks (NOT part of the frozen section)

Also outside the lock. These change how a rule is *enforced*, not what it says.

**The launcher lives here.** The steering study had eight places that started the
server and seven lacked `-notexturestreaming`. One launcher in that repo fixed that
repo, and the others then called it by an absolute path into that checkout. So:

    python3 -m carla_determinism launch  --port 3000 --map Town04 [--windowed]
    python3 -m carla_determinism restart --port 3000 --map Town04
    python3 -m carla_determinism stop    --port 3000

`launch` refuses an occupied port, starts the server with the D-3 and D-5 flags,
waits until `get_world()` answers rather than until the port binds, loads the map, and
runs the preflight against the real `/proc` command line. `--extra` may add UE4 flags
and cannot remove a rule flag. Study gates, such as a photometry reference, run in the
study after `launch` returns 0.

**D-4 and D-6 now have checks.** `require_camera(blueprint)` refuses a camera whose
post-processing is off or whose exposure is not manual, at the one moment those can be
read. `require_sole_client(port, expected)` refuses when more connections than the
caller expects hold the port; the caller states the expectation because a traffic
manager holds one of its own, and a guess would give false positives.

**The audit catches the code before the run.**

    python3 -m carla_determinism audit .                 # exit 1 on a finding
    python3 -m carla_determinism audit --install-hook    # as a git pre-commit hook

A-1 is a raw `.apply_control(` outside the package (D-2). A-2 is CarlaUE4 started
outside a declared launcher (D-3, D-5). A-3 is `CARLA_SKIP_PREFLIGHT`. A-4 is a
dependency on this package that is missing or not pinned to an exact tag. Allowances
live in `.carla-determinism-audit` at the repository root, or on one line as
`# carla-determinism: allow, <reason>`. An allowance is visible in the diff. An
escape hatch in the environment is not.

**A Claude Code hook refuses a hand launch.** `python3 -m carla_determinism
claude-hook` reads the PreToolUse payload and exits 2 when a Bash command would start
CarlaUE4 outside a launcher. One entry in `~/.claude/settings.json` covers every
repository on the machine. See the README for the entry.
