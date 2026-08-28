"""Preflight for RULES.md. Refuses to let a measurement run on a misconfigured server.

A document gets skimmed; a raise cannot be. D-3 and D-5 are LAUNCH flags and invisible
over the Python API, so they are read from the server's real command line in /proc. A
server someone started by hand without them answers RPC completely normally and every
result it produces is quietly noisier.
"""
import argparse
import os
import re
import sys

from ._lock import check_lock, digest, write_lock

REQUIRED_LAUNCH = ("-notexturestreaming",)   # D-3
REQUIRED_QUALITY = "Epic"                    # D-5


def server_cmdline(port):
    """Launch arguments of the CARLA serving `port`, from /proc.

    Matched on the rpc-port, never on the process name: kill-and-match-by-name has
    already taken down another user's simulator once, and a second server on another
    port must never be mistaken for this one.
    """
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = fh.read().decode(errors="replace").split("\0")
        except OSError:
            continue
        if not argv or "CarlaUE4" not in argv[0]:
            continue
        if any(f"-carla-rpc-port={port}" in a for a in argv):
            return argv
    return None


def check_server(port, world=None, fixed_dt=None, deterministic_control=None,
                 in_run=True):
    """Collect rule violations. Returns a list of strings; empty means compliant.

    Study-specific values are PARAMETERS, not imports: this package must not reach into
    any study's config, or it cannot be shared by studies whose timesteps differ.
    """
    problems = []

    argv = server_cmdline(port)
    if argv is None:
        problems.append(
            f"D-3/D-5: no CarlaUE4 server found serving rpc-port {port}; cannot verify "
            f"its launch flags")
    else:
        joined = " ".join(argv)
        for flag in REQUIRED_LAUNCH:
            if flag not in joined:
                problems.append(
                    f"D-3: server on port {port} was NOT launched with {flag}. Texture "
                    f"streaming is the dominant render entropy source (168x).")
        m = re.search(r"-quality-level=(\w+)", joined)
        q = m.group(1) if m else "(unset)"
        if q != REQUIRED_QUALITY:
            problems.append(f"D-5: quality-level is {q}, must be {REQUIRED_QUALITY}.")

    if deterministic_control is False:
        problems.append(
            "D-2: deterministic control is off, so vehicle commands use the "
            "fire-and-forget RPC that diverges the first time a command changes.")

    # D-1 is a PER-RUN setting: it is applied at the start of a run and restored at the
    # end, so an IDLE server is legitimately asynchronous. Flagging that would be a
    # false positive, and false positives train people to ignore the check.
    if world is not None:
        s = world.get_settings()
        if not s.synchronous_mode:
            if in_run:
                problems.append("D-1: world is not in synchronous mode.")
            return problems
        if fixed_dt is not None and abs((s.fixed_delta_seconds or 0.0) - fixed_dt) > 1e-9:
            problems.append(
                f"D-1: fixed_delta_seconds is {s.fixed_delta_seconds}, expected {fixed_dt}.")
        if not getattr(s, "substepping", False):
            problems.append("D-1: substepping is off.")
        else:
            covered = s.max_substeps * s.max_substep_delta_time
            if covered + 1e-12 < (s.fixed_delta_seconds or 0.0):
                problems.append(
                    f"D-1: substeps cover {covered:.4f}s of a {s.fixed_delta_seconds}s "
                    f"step; physics will silently advance less than the full step.")
    return problems


def require_deterministic(port, world=None, fixed_dt=None, deterministic_control=None):
    """Raise unless the live simulator satisfies the rules. Call before measuring."""
    problems = check_lock() + check_server(
        port, world, fixed_dt, deterministic_control, in_run=True)
    if problems:
        raise SystemExit(
            "CARLA DETERMINISM PREFLIGHT FAILED -- refusing to produce a measurement.\n"
            "See carla_determinism/RULES.md.\n  " + "\n  ".join(problems))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python3 -m carla_determinism")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CARLA_PORT", "2000")))
    ap.add_argument("--fixed-dt", type=float, default=None)
    ap.add_argument("--write", action="store_true",
                    help="regenerate the lock (amendment procedure only)")
    ap.add_argument("--lock-only", action="store_true")
    args = ap.parse_args(argv)

    if args.write:
        print(f"  wrote RULES.lock\n  {write_lock()}")
        return 0

    problems = check_lock()
    if not args.lock_only:
        problems += check_server(args.port, None, args.fixed_dt, None, in_run=False)

    if problems:
        print("  DETERMINISM PREFLIGHT FAILED:")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("  determinism preflight OK (lock intact; D-3/D-5 verified on the live server)")
    print("  D-7 floor remains: closed-loop numbers are still RATES over >=10 repetitions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
