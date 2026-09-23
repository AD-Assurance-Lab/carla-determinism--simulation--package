# carla-determinism

Operating rules for getting repeatable numbers out of the CARLA simulator, and a
preflight check that enforces them. The rules are in `src/carla_determinism/RULES.md`.
Section 4 of that file is the only way to change a rule, and a hash lock catches other edits.

    pip install git+https://github.com/AD-Assurance-Lab/carla-determinism--simulation--package@v1.3.2
    pip install -e . && python -m pytest                          # from a checkout, in a venv

    python3 -m carla_determinism --port 3000                      # check a live server
    python3 -m carla_determinism launch --port 3000 --map Town04  # start a server with the flags
    python3 -m carla_determinism audit .                          # audit a study repository

In a study, call `require_deterministic` where the code turns on synchronous mode, and send
every vehicle command through `apply_control`. The other commands are `restart`, `stop`,
`provenance` and `claude-hook`.

The rules make run-to-run noise much smaller, but they do not remove it. Report each
closed-loop number as a rate over repeated runs. `docs/` holds a health check of the
package and the open requests to change a rule.
