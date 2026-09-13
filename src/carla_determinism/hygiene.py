"""Session hygiene: the rules about WHICH server you are measuring on.

`preflight` answers "is this server configured correctly?" -- a launch-time property.
These answer a different question that cost just as much: "is this server FRESH, and is
this world EMPTY?" A correctly configured server that has been up for hours, or that
still holds a killed run's vehicle, produces data that is well-formed and wrong.

Both rules existed as prose in each repo and were re-typed into each new driver script,
so they drifted the moment a driver was added. Measured in
`formal-verification--steering--code` on 2026-08-30:

  * one capture driver restarted before every capture; its sibling restarted NOT AT ALL
    and took all 24 verification captures for a deployment-test certificate in a single
    server session;
  * a killed capture left its vehicle and camera alive, because SIGTERM does not run
    Python cleanup, and the next capture rendered a road with a parked car on it.

Neither is visible downstream: the arrays are the right shape and full of plausible
frames. So the checks belong at the choke point every measurement passes through, not in
the scripts that must remember to call them.
"""
import os
import signal
import time

DEFAULT_MAX_SERVER_AGE_S = 3600.0     # ~10.5 GiB leaked per 11 h; an hour is generous


def server_age_s(port):
    """Seconds since the CARLA server on `port` started, or None if not found.

    Read from /proc rather than asked over RPC: a degraded server answers RPC perfectly
    well, which is the entire problem.
    """
    from .preflight import server_pid
    pid = server_pid(port)
    if pid is None:
        return None
    try:
        with open("/proc/uptime") as fh:
            uptime = float(fh.read().split()[0])
        with open(f"/proc/{pid}/stat") as fh:
            starttime = float(fh.read().rsplit(")", 1)[1].split()[19])
    except (OSError, IndexError, ValueError):
        return None
    hz = os.sysconf("SC_CLK_TCK")
    return max(0.0, uptime - starttime / hz)


def require_fresh_server(port, max_age_s=DEFAULT_MAX_SERVER_AGE_S):
    """R-SIM-1 as a CHECK rather than a habit: refuse to measure on a stale server.

    A CARLA server degrades silently -- it keeps answering, keeps reporting plausible
    velocities, and stops advancing physics correctly. Measured on a degraded server:
    sections drove 14-62% of their length at 1.3-5.6 m/s while the speed readout said
    20.0 throughout. Restarted, the same code and checkpoint scored 0/6.
    """
    age = server_age_s(port)
    if age is None:
        return None
    if age > max_age_s:
        raise RuntimeError(
            f"REFUSING to measure: the CARLA server on port {port} has been up for "
            f"{age / 60:.0f} minutes (limit {max_age_s / 60:.0f}).\n"
            "    A server degrades silently: it keeps answering and stops advancing\n"
            "    physics, and nothing in the result reveals which server produced it.\n"
            "    Restart it first (R-SIM-1), then measure.")
    return age


def require_clean_world(world):
    """Refuse to measure in a world that already contains actors.

    A killed run leaks its vehicle and camera, and the next measurement then renders a
    road with someone else's car parked on it.
    """
    stale = [a for a in world.get_actors()
             if a.type_id.startswith(("vehicle.", "sensor."))]
    if stale:
        listing = "\n".join(f"      {a.id} {a.type_id}" for a in stale[:8])
        raise RuntimeError(
            f"REFUSING to measure: {len(stale)} actor(s) already alive in this world.\n"
            f"{listing}\n"
            "    A previous run leaked them -- SIGTERM skips Python cleanup. Measuring\n"
            "    here renders a road with another run's vehicle on it, which no array\n"
            "    shape or verdict can reveal. Restart the server (R-SIM-1).")
    return True


def install_cleanup_handlers():
    """Make SIGTERM and SIGINT unwind normally so `finally` blocks actually run.

    Python's default SIGTERM handler exits without unwinding, so a killed measurement
    never reaches its teardown and its actors outlive it. Raising turns the signal into
    an ordinary exception and the existing cleanup executes.
    """
    def _raise(signum, _frame):
        raise KeyboardInterrupt(f"signal {signum}")

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _raise)
        except (ValueError, OSError):
            pass          # not on the main thread; nothing to install
    return True


def require_measurable(port, world, max_age_s=DEFAULT_MAX_SERVER_AGE_S):
    """The one call a measurement should make: fresh server, empty world, clean exit."""
    install_cleanup_handlers()
    age = require_fresh_server(port, max_age_s=max_age_s)
    require_clean_world(world)
    return age
