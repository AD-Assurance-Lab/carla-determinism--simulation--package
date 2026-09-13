"""One record of the harness a measurement ran under.

D-11 says data from a violating harness is not reusable. That is enforceable only if
the artifact says which harness produced it. This is that record. Every study had a
private copy of it; a copy drifts, so it lives here.

    stamp = cd.provenance(port, world, deterministic_control=True)
    json.dump(stamp, fh)

Unknown is recorded as None, never as False. "Not checked" and "checked and wrong"
must stay different in the record, or the record cannot be trusted later.
"""
import platform
import sys

from ._lock import check_lock, digest
from .cuda import torch_provenance
from .hygiene import server_age_s
from .preflight import server_cmdline


def world_settings(world):
    """The D-1 settings as a dict, or None when there is no world."""
    if world is None:
        return None
    try:
        s = world.get_settings()
        return {
            "synchronous_mode": bool(s.synchronous_mode),
            "fixed_delta_seconds": s.fixed_delta_seconds,
            "substepping": bool(getattr(s, "substepping", False)),
            "max_substeps": getattr(s, "max_substeps", None),
            "max_substep_delta_time": getattr(s, "max_substep_delta_time", None),
        }
    except Exception:
        return None


def provenance(port=None, world=None, deterministic_control=None):
    """The harness, as a JSON-ready dict. Nothing in it changes the harness."""
    from . import __version__
    lock_problems = check_lock()
    argv = server_cmdline(port) if port is not None else None
    return {
        "package_version": __version__,
        "rules_digest": digest(),
        "lock_ok": not lock_problems,
        "lock_problems": lock_problems,
        "port": port,
        "server_argv": argv,
        "server_age_s": server_age_s(port) if port is not None else None,
        "deterministic_control": deterministic_control,
        "world_settings": world_settings(world),
        "python": sys.version.split()[0],
        "hostname": platform.node(),
        "torch": torch_provenance(),
    }
