# carla-determinism

Measured operating rules for getting reproducible numbers out of CARLA, and the preflight
that enforces them.

**This is not a standard.** The lab works to actual standards — ISO 26262, ISO 21448,
FMVSS — and this is not one of them. It is an internal operating procedure for our own
simulator, with the same weight as any other lab procedure.

**Read `src/carla_determinism/RULES.md`.** It is the content; everything else here is
machinery to stop it being ignored or quietly edited.

## Why it exists

A steering study's competence gate reported "held 2/3" for a checkpoint that had not
changed between runs. CARLA was in synchronous mode with a fixed timestep, pinned spawn,
pinned weather and pinned camera exposure, so that should have been impossible.

It was not, for two reasons, both found by cutting the feedback loop and driving a
scripted command sequence instead:

1. **Synchronous mode synchronises the tick, not the command queue feeding it.**
   `vehicle.apply_control()` is fire-and-forget and races `world.tick()`. Three
   repetitions of one identical scripted run finished **60 m apart**.
2. **UE4 streams texture mips asynchronously**, so mip residency depends on load timing
   rather than world state. `-notexturestreaming` cut the steering noise the renderer
   injects by **168x**.

Neither is visible in a result. Both trajectories look physically plausible.

## Install

    pip install git+https://github.com/AD-Assurance-Lab/carla-determinism--simulation--package@v1.0.0

Or, for local development against a checkout beside your study repo:

    pip install -e ../carla-determinism--simulation--package

## Use

    import carla_determinism as cd

    client = carla.Client(host, port)
    cd.bind_client(client)                       # once, at connect

    # ... enable synchronous mode, then, before producing any measurement:
    cd.require_deterministic(port, world, fixed_dt=0.2, deterministic_control=True)

    # every driving loop, every study:
    cd.apply_control(vehicle, carla.VehicleControl(throttle=t, brake=b, steer=s))

Command line:

    python3 -m carla_determinism --port 3000

## What it does NOT give you

Bit-exact closed-loop replay. That is unreachable (rule D-7): a scene where nothing moves
at all still renders ~30 differing pixels of 307,200 across repetitions. **Every
closed-loop number remains a rate over at least 10 repetitions with a confidence
interval.** These rules make the noise 168x smaller and name its source; they do not
remove it.

And note rule D-10: with physics bit-exact, a 2.6e-6 steering perturbation still grew to
7.6 ft of cross-track error over 349 steps. That amplification is a property of the
*policy*, not the simulator. Run-to-run spread is a stability-margin measurement, not
only instrument noise.

## Changing a rule

Section 4 of `RULES.md`. The frozen section is hash-locked; edit it and the preflight
fails until the lock is regenerated in the same commit, with the contradicting
measurement recorded. A rule may not be relaxed because a run is inconvenient.
