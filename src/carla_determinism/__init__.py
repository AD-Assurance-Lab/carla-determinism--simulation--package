"""CARLA determinism rules, and the code that enforces them.

Not a standard -- the lab works to actual standards (ISO 26262, ISO 21448, FMVSS) and
this is not one of them. It is an internal operating procedure for our own simulator.

    import carla_determinism as cd

    client = carla.Client(host, port)
    cd.bind_client(client)
    cd.require_deterministic(port, world, fixed_dt=0.2, deterministic_control=True)
    ...
    cd.apply_control(vehicle, control)

The rules themselves are in RULES.md next to this file, hash-locked by RULES.lock.
"""
from pathlib import Path

from ._lock import RULES, LOCK, check_lock, digest, frozen_text, write_lock
from .control import apply_control, bind_client, get_client
from .hygiene import (DEFAULT_MAX_SERVER_AGE_S, install_cleanup_handlers,
                      require_clean_world, require_fresh_server, require_measurable,
                      server_age_s)
from .preflight import (carla_processes, check_server, require_deterministic,
                        server_cmdline, server_pid, serves_port)

__version__ = "1.1.0"
RULES_PATH = Path(RULES)

__all__ = [
    "apply_control", "bind_client", "get_client",
    "require_deterministic", "check_server", "server_cmdline", "server_pid",
    "carla_processes", "serves_port",
    "check_lock", "digest", "frozen_text", "write_lock",
    "RULES_PATH", "RULES", "LOCK", "__version__",
    "require_measurable",
    "require_fresh_server",
    "require_clean_world",
    "install_cleanup_handlers",
    "server_age_s",
    "DEFAULT_MAX_SERVER_AGE_S",
]
