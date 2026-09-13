"""`python3 -m carla_determinism <command>`.

    (none) / verify   the preflight against the live server; exit 1 on violation
    launch            start a server with the rule flags, wait, preflight
    stop              stop the server on a port, by rpc-port only
    restart           stop, then launch
    provenance        print the harness record as JSON
    audit             static audit of a repository (pre-commit, CI)
    claude-hook       a PreToolUse hook that refuses a hand launch of CarlaUE4

The bare form is unchanged, so every existing launcher that calls
`python3 -m carla_determinism --port N` keeps working.
"""
import argparse
import json
import os
import sys

from . import launcher, preflight
from .audit import LAUNCH, main as audit_main

COMMANDS = ("verify", "launch", "stop", "restart", "provenance", "audit", "claude-hook")


def _port_default():
    return int(os.environ.get("CARLA_PORT", "2000"))


def _launch_parser(prog):
    ap = argparse.ArgumentParser(prog=prog)
    ap.add_argument("--port", type=int, default=_port_default())
    ap.add_argument("--carla-root", default=os.environ.get("CARLA_ROOT", "~/carla"))
    ap.add_argument("--map", dest="map_name", default=os.environ.get("STUDY_MAP"))
    ap.add_argument("--windowed", action="store_true")
    ap.add_argument("--display", default=None)
    ap.add_argument("--res", default="1280x720")
    ap.add_argument("--log", default=os.environ.get("CARLA_LOG"))
    ap.add_argument("--timeout", type=float, default=launcher.DEFAULT_TIMEOUT_S)
    ap.add_argument("--require-cuda", action="store_true")
    ap.add_argument("--fixed-dt", type=float, default=None)
    ap.add_argument("--extra", action="append", default=[],
                    help="an additional UE4 flag; rule flags cannot be overridden")
    return ap


def _launch_kwargs(args):
    w, h = (int(x) for x in args.res.lower().split("x"))
    return dict(carla_root=args.carla_root, map_name=args.map_name, windowed=args.windowed,
                res=(w, h), extra=tuple(args.extra), log_path=args.log,
                timeout_s=args.timeout, need_cuda=args.require_cuda,
                fixed_dt=args.fixed_dt, display=args.display)


def claude_hook(stdin=sys.stdin, stderr=sys.stderr):
    """PreToolUse hook for Claude Code. Exit 2 blocks the tool call and shows why.

    A session that starts CarlaUE4 by hand starts it without the flags. Only the
    package launcher, or a launcher the repository declares, may start it.
    """
    try:
        payload = json.load(stdin)
    except Exception:
        return 0
    cmd = str((payload.get("tool_input") or {}).get("command", ""))
    if not LAUNCH.search(cmd):
        return 0
    if "carla_determinism" in cmd and ("launch" in cmd or "restart" in cmd):
        return 0
    if "carla_launch" in cmd or "carla_restart" in cmd:
        return 0
    if cmd.lstrip().startswith(("pkill", "pgrep", "ps ", "grep", "cat ", "ls ")):
        return 0
    print("carla-determinism: refusing a hand launch of CarlaUE4. It would start without "
          "-notexturestreaming and -quality-level=Epic (D-3, D-5).\n"
          "Use: python3 -m carla_determinism launch --port N --map M, or the repository's "
          "declared launcher.", file=stderr)
    return 2


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv and argv[0] in COMMANDS else None
    rest = argv[1:] if cmd else argv

    if cmd in (None, "verify"):
        return preflight.main(rest)

    if cmd == "audit":
        return audit_main(rest)

    if cmd == "claude-hook":
        return claude_hook()

    if cmd == "provenance":
        ap = argparse.ArgumentParser(prog="python3 -m carla_determinism provenance")
        ap.add_argument("--port", type=int, default=_port_default())
        args = ap.parse_args(rest)
        from .provenance import provenance
        print(json.dumps(provenance(args.port), indent=2))
        return 0

    if cmd == "stop":
        ap = argparse.ArgumentParser(prog="python3 -m carla_determinism stop")
        ap.add_argument("--port", type=int, default=_port_default())
        args = ap.parse_args(rest)
        launcher.stop(args.port)
        print(f"  nothing serves port {args.port}")
        return 0

    ap = _launch_parser(f"python3 -m carla_determinism {cmd}")
    args = ap.parse_args(rest)
    fn = launcher.restart if cmd == "restart" else launcher.launch
    info = fn(args.port, **_launch_kwargs(args))
    print(f"  CARLA pid {info['pid']} serves port {info['port']} on {info['map']} "
          f"({info['mode']}); log {info['log']}")
    return 0
