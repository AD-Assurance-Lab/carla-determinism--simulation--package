"""The launcher, in the package, so the flags cannot go missing.

The steering study had eight places that started the server. Seven lacked
`-notexturestreaming`. One launcher in that repo fixed it for that repo, and the other
studies then called it by an absolute path into that checkout. A path into another
checkout breaks on the next machine, so the launcher lives here and each study calls:

    python3 -m carla_determinism launch  --port 3000 --map Town04
    python3 -m carla_determinism stop    --port 3000
    python3 -m carla_determinism restart --port 3000 --map Town04

What `launch` does, in order:

  1. refuses if anything already serves the port. A launch that reuses whatever was
     there measures a server nobody asked for; `restart` stops it first.
  2. starts CarlaUE4.sh detached, with the rpc-port, `-quality-level=Epic`,
     `-notexturestreaming`, and either `-RenderOffScreen` or `-windowed`.
  3. waits until get_world() answers, not until the port binds, and loads `--map` if
     asked. It never outlives `--timeout`.
  4. runs the preflight against the server's real /proc command line.
  5. with `--require-cuda`, proves the GPU can run a kernel, not merely that it exists.

Study-specific gates, such as a photometry reference, run in the study after this
returns 0. They are not rules; they are that study's measurements.
"""
import os
import signal
import subprocess
import sys
import time

from . import preflight
from .preflight import REQUIRED_LAUNCH, REQUIRED_QUALITY

DEFAULT_TIMEOUT_S = 240.0
DEFAULT_RES = (1280, 720)


def launch_argv(port, windowed=False, res=DEFAULT_RES, extra=()):
    """The command line, flags first. `extra` may add UE4 flags, never remove these."""
    for a in extra:
        low = a.lower()
        if low.startswith("-quality-level") or low.startswith("-carla-rpc-port") \
                or low in ("-windowed", "-renderoffscreen"):
            raise ValueError(f"launch_argv: {a!r} is a rule flag and cannot be overridden "
                             f"through `extra`.")
    argv = ["./CarlaUE4.sh", f"-carla-rpc-port={port}", f"-quality-level={REQUIRED_QUALITY}"]
    argv += list(REQUIRED_LAUNCH)
    if windowed:
        argv += ["-windowed", f"-ResX={res[0]}", f"-ResY={res[1]}"]
    else:
        argv += ["-RenderOffScreen"]
    return argv + list(extra)


def start_server(carla_root, argv, log_path, display=None):
    """Start the server detached. The child gets no descriptor of ours.

    A detached server that inherits the caller's descriptors holds them for its whole
    life: a restart lock on fd 9 once stayed held until the server died.
    """
    carla_root = os.path.expanduser(carla_root)
    script = os.path.join(carla_root, "CarlaUE4.sh")
    if not os.access(script, os.X_OK):
        raise SystemExit(f"FATAL: {script} is not an executable; set --carla-root.")
    os.makedirs(os.path.dirname(os.path.abspath(log_path)) or ".", exist_ok=True)
    env = dict(os.environ)
    if display:
        env["DISPLAY"] = display
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(argv, cwd=carla_root, env=env, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True, close_fds=True)
    return proc.pid


def wait_ready(port, timeout_s=DEFAULT_TIMEOUT_S, map_name=None, host="127.0.0.1",
               poll_s=5.0):
    """Block until get_world() answers, load `map_name` if asked. Returns the map name.

    A bound port is not a ready simulator. A gate once drove for 12 minutes against a
    listening-but-unready server and recorded the failure as the students' failure.
    """
    import carla
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout_s:
        try:
            c = carla.Client(host, port)
            c.set_timeout(30.0)
            w = c.get_world()
            m = w.get_map().name
            if map_name and map_name.lower() not in m.lower():
                left = timeout_s - (time.time() - t0)
                if left < 0.4 * timeout_s:
                    raise TimeoutError(f"no time left to load {map_name} within "
                                       f"{timeout_s:.0f}s (server is on {m})")
                c.set_timeout(min(120.0, max(20.0, left)))
                w = c.load_world(map_name)
                m = w.get_map().name
            return m
        except TimeoutError:
            raise
        except Exception as exc:
            last = str(exc).split("\n")[0][:90]
            time.sleep(poll_s)
    raise TimeoutError(f"CARLA not ready on {port} after {timeout_s:.0f}s. "
                       f"Last error: {last}")


def _wrapper_pids(port):
    """PIDs of shell wrappers (CarlaUE4.sh) that carry this port; the binary is found
    by server_pid. Both must go, or the wrapper restarts nothing and lingers."""
    want = f"-carla-rpc-port={port}"
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                argv = fh.read().decode(errors="replace").split("\0")
        except OSError:
            continue
        if any("CarlaUE4.sh" in a for a in argv[:2]) and want in argv:
            out.append(int(pid))
    return out


def stop(port, grace_s=15.0):
    """Stop the server on `port`, by rpc-port only. SIGTERM, then SIGKILL. Returns
    True when nothing serves the port any more; raises when something still does."""
    pids = set(_wrapper_pids(port))
    p = preflight.server_pid(port)
    if p is not None:
        pids.add(p)
    if not pids and not preflight.port_listening(port):
        return True
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        t0 = time.time()
        while time.time() - t0 < grace_s:
            if preflight.server_pid(port) is None and not preflight.port_listening(port):
                return True
            time.sleep(0.5)
    raise RuntimeError(f"FATAL: port {port} is still held after SIGKILL; something "
                       f"else owns it.")


def require_cuda():
    """The GPU must be USABLE, not merely present. nvidia_uvm wedges after many rapid
    restarts: the card looks healthy and torch.cuda.is_available() is False."""
    try:
        import torch
        torch.zeros(8, device="cuda")
    except Exception as exc:
        raise SystemExit(
            f"FATAL: the GPU is present but CUDA cannot initialise "
            f"({type(exc).__name__}: {exc}).\n"
            "  nvidia_uvm is probably wedged. In a terminal:\n"
            "      sudo modprobe -r nvidia_uvm && sudo modprobe nvidia_uvm")


def launch(port, carla_root="~/carla", map_name=None, windowed=False, res=DEFAULT_RES,
           extra=(), log_path=None, timeout_s=DEFAULT_TIMEOUT_S, need_cuda=False,
           fixed_dt=None, display=None, out=sys.stdout):
    """Launch, wait, preflight. Returns a dict about the server. Raises SystemExit."""
    if preflight.server_cmdline(port) is not None or preflight.port_listening(port):
        argv = preflight.server_cmdline(port)
        raise SystemExit(
            f"FATAL: something already serves port {port}"
            + (f": {' '.join(a for a in argv[1:] if a)}" if argv else "") + "\n"
            "  A launch that reuses it would measure a server nobody asked for.\n"
            "  Run `python3 -m carla_determinism restart`, which stops it first.")
    if windowed and not (display or os.environ.get("DISPLAY")):
        raise SystemExit("FATAL: --windowed but no DISPLAY. Pass --display or run headless.")
    if need_cuda:
        require_cuda()

    argv = launch_argv(port, windowed=windowed, res=res, extra=extra)
    log_path = log_path or os.path.join(os.getcwd(), f"carla-{port}.log")
    mode = "windowed" if windowed else "headless"
    print(f"  launching CARLA {mode} on port {port}: {' '.join(argv[1:])}", file=out,
          flush=True)
    pid = start_server(carla_root, argv, log_path, display=display)

    t0 = time.time()
    try:
        m = wait_ready(port, timeout_s=timeout_s, map_name=map_name)
    except TimeoutError as exc:
        raise SystemExit(f"FATAL: {exc}\n  server log: {log_path}")
    print(f"  ready after {time.time() - t0:.0f}s on {m}", file=out, flush=True)

    problems = preflight.check_server(port, None, fixed_dt, None, in_run=False)
    if problems:
        raise SystemExit("FATAL: the server just launched violates the rules:\n  "
                         + "\n  ".join(problems))
    real = preflight.server_cmdline(port)
    print("  preflight OK; real argv: " + " ".join(a for a in real[1:] if a), file=out,
          flush=True)
    return {"port": port, "pid": pid, "map": m, "argv": real, "log": log_path,
            "mode": mode}


def restart(port, **kw):
    stop(port)
    return launch(port, **kw)
