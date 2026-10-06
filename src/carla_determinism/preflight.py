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


def carla_processes():
    """Yield (pid, argv) for every CarlaUE4 process in /proc."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = fh.read().decode(errors="replace").split("\0")
        except OSError:
            continue
        if argv and "CarlaUE4" in argv[0]:
            yield int(pid), argv


def serves_port(argv, port):
    """True if this command line names `port` as its rpc-port, exactly.

    Exact, not a substring: `-carla-rpc-port=300` is contained in
    `-carla-rpc-port=3000`, and a wrong-server match is the worst kind of wrong.
    """
    want = f"-carla-rpc-port={port}"
    return any(a.strip() == want for a in argv)


def server_pid(port):
    """PID of the CARLA serving `port`, or None."""
    for pid, argv in carla_processes():
        if serves_port(argv, port):
            return pid
    return None


def server_cmdline(port):
    """Launch arguments of the CARLA serving `port`, from /proc.

    Matched on the rpc-port, never on the process name: kill-and-match-by-name has
    already taken down another user's simulator once, and a second server on another
    port must never be mistaken for this one.
    """
    for _pid, argv in carla_processes():
        if serves_port(argv, port):
            return argv
    return None


def tcp_entries():
    """(state, local_port, remote_port) for every IPv4 and IPv6 socket in /proc."""
    out = []
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path) as fh:
                lines = fh.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if len(f) < 4:
                continue
            try:
                out.append((f[3], int(f[1].rsplit(":", 1)[1], 16),
                            int(f[2].rsplit(":", 1)[1], 16)))
            except (IndexError, ValueError):
                continue
    return out


TCP_ESTABLISHED, TCP_LISTEN = "01", "0A"


def port_listening(port, entries=None):
    entries = tcp_entries() if entries is None else entries
    return any(st == TCP_LISTEN and lp == port for st, lp, _rp in entries)


def client_count(port, entries=None):
    """Established connections INTO `port`. In synchronous mode every one of them can
    tick the world (D-6). Note the traffic manager holds one of its own."""
    entries = tcp_entries() if entries is None else entries
    return sum(1 for st, lp, _rp in entries if st == TCP_ESTABLISHED and lp == port)


def _bp_attr(bp, name):
    """A camera blueprint attribute as a lower-case string, or None when unreadable.

    CARLA casts strictly: as_str() on a Bool attribute raises. Measured on 0.9.16,
    where enable_postprocess_effects is Bool and exposure_mode is String. So try each
    cast, and fall back to the value= field of the attribute's own repr.
    """
    try:
        if hasattr(bp, "has_attribute") and not bp.has_attribute(name):
            return None
        a = bp.get_attribute(name)
    except Exception:
        return None
    for cast in ("as_str", "as_bool", "as_int", "as_float"):
        fn = getattr(a, cast, None)
        if fn is None:
            continue
        try:
            return str(fn()).strip().lower()
        except Exception:
            continue
    m = re.search(r"value=([^,)]*)", str(a))
    return m.group(1).strip().lower() if m else None


def check_camera(bp):
    """D-4 against a camera blueprint, before it is spawned.

    Post-processing must stay ON and exposure must be MANUAL. Manual exposure lives
    inside the post-process chain, so turning the chain off silently un-pins it
    [postprocess off measured ~2000x worse]. Both are blueprint attributes, so this is
    the one moment they can be read.
    """
    problems = []
    pp = _bp_attr(bp, "enable_postprocess_effects")
    if pp is None:
        problems.append("D-4: cannot read enable_postprocess_effects on this blueprint.")
    elif pp.strip().lower() != "true":
        problems.append(f"D-4: enable_postprocess_effects is {pp}; it must stay true, "
                        f"or manual exposure is silently un-pinned.")
    mode = _bp_attr(bp, "exposure_mode")
    if mode is None:
        problems.append("D-4: cannot read exposure_mode on this blueprint.")
    elif mode.strip().lower() != "manual":
        problems.append(f"D-4: exposure_mode is {mode}; it must be manual.")
    return problems


def require_camera(bp):
    """Raise unless the camera blueprint satisfies D-4. Call before spawning it."""
    problems = check_camera(bp)
    if problems:
        raise SystemExit(
            "CARLA DETERMINISM PREFLIGHT FAILED -- refusing to spawn this camera.\n"
            "See carla_determinism/RULES.md D-4.\n  " + "\n  ".join(problems))


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
    if args.lock_only:
        print("  determinism lock OK (RULES.md frozen rules match RULES.lock)")
        return 0
    print("  determinism preflight OK (lock intact; D-3/D-5 verified on the live server)")
    print("  D-7 (A-1): three repetitions per cell, each on a fresh server; repetitions that disagree VOID the cell")
    return 0


if __name__ == "__main__":
    sys.exit(main())
