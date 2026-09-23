# carla-determinism

Operating rules for repeatable CARLA runs, and a preflight check that enforces them. The
rules are in `src/carla_determinism/RULES.md`. `docs/` holds a health check of the package
and requests to change a rule.

    pip install -e . && python -m pytest

    python3 -m carla_determinism --port 3000                      # check a live server
    python3 -m carla_determinism launch --port 3000 --map Town04  # start a server
    python3 -m carla_determinism audit .                          # audit a study repository

In a study, call `require_deterministic` where the code turns on synchronous mode, and send
vehicle commands through `apply_control`.
