"""A static audit of a study repository, for a pre-commit hook and CI.

The runtime preflight catches a wrong server. This catches the code that would drive
one, at commit time, in about a second, with no simulator:

  A-1  a raw `.apply_control(` whose receiver is not the package (D-2)
  A-2  CarlaUE4 started outside a declared launcher (D-3, D-5)
  A-3  an escape hatch: CARLA_SKIP_PREFLIGHT
  A-4  the dependency on this package is missing, or not pinned to an exact tag

    python3 -m carla_determinism audit .                # exit 1 on any finding
    python3 -m carla_determinism audit --install-hook   # .git/hooks/pre-commit

Per-repository allowances live in `.carla-determinism-audit` at the root, one per line:

    allow-receiver env          # env.apply_control is this repo's choke point
    launcher scripts/simulator/carla_launch.sh
    exempt tests/test_harness.py    # fixtures that quote the patterns on purpose
    exempt-dependency runs in ../multi-condition/.venv, which pins the package

A single line is allowed with a trailing comment that says why:

    vehicle.apply_control(control)   # carla-determinism: allow, the D-2 fallback path

An allowance is visible in the diff. An escape hatch in the environment is not.
"""
import os
import re
import sys

RAW_CONTROL = re.compile(r"(?<![\w.])([A-Za-z_][\w.]*)\.apply_control\(")
LAUNCH = re.compile(r"CarlaUE4(?:\.sh|-Linux-Shipping)")
SKIP = "CARLA_SKIP_PREFLIGHT"
DEP = re.compile(r"carla[-_]determinism")
PIN = re.compile(r"carla[-_]determinism\s*(?:@\s*\S+@v\d+\.\d+\.\d+\b|==\s*\d+\.\d+\.\d+\b)")

DEFAULT_RECEIVERS = ("cd", "_cd", "carla_determinism")
SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", "node_modules",
             ".pytest_cache", ".mypy_cache", ".ruff_cache"}
CONFIG = ".carla-determinism-audit"
ALLOW = "carla-determinism: allow"
HOOK_MARK = "# carla-determinism audit hook"


class Finding:
    def __init__(self, code, path, line, text):
        self.code, self.path, self.line, self.text = code, path, line, text

    def __str__(self):
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.code} {where}: {self.text}"


def read_config(root):
    receivers, launchers, exempt = set(DEFAULT_RECEIVERS), set(), set()
    dep_reason = None
    path = os.path.join(root, CONFIG)
    if os.path.isfile(path):
        with open(path) as fh:
            for raw in fh:
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                key, _, val = line.partition(" ")
                val = val.strip()
                if key == "allow-receiver" and val:
                    receivers.add(val)
                elif key == "launcher" and val:
                    launchers.add(os.path.normpath(val))
                elif key == "exempt" and val:
                    exempt.add(os.path.normpath(val))
                elif key == "exempt-dependency" and val:
                    dep_reason = val
    return receivers, launchers, exempt, dep_reason


def _source_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info")]
        for fn in filenames:
            if fn.endswith((".py", ".sh")):
                yield os.path.join(dirpath, fn)


def _code_lines(path):
    """(lineno, text) for lines that are code: no comments, no docstring bodies.
    A rule quoted in a docstring is not a violation; a call is."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    in_doc = False
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if path.endswith(".py"):
            n = stripped.count('"""') + stripped.count("'''")
            if in_doc:
                if n % 2 == 1:
                    in_doc = False
                continue
            if n % 2 == 1:
                in_doc = True
                continue
            if n >= 2:
                continue                       # one-line docstring
        if not stripped or stripped.startswith("#") or ALLOW in line:
            continue
        yield i, line.split("#", 1)[0] if not path.endswith(".py") else line


def _is_own_package(root):
    try:
        with open(os.path.join(root, "pyproject.toml")) as fh:
            return re.search(r'^name\s*=\s*"carla-determinism"', fh.read(), re.M) is not None
    except OSError:
        return False


def check_dependency(root):
    """A-4. Consumers pin an exact tag, so a rule change cannot arrive mid-study."""
    if _is_own_package(root):
        return []
    names = ["pyproject.toml", "setup.py", "setup.cfg"]
    try:
        names += sorted(f for f in os.listdir(root) if re.match(r"requirements.*\.txt$", f))
    except OSError:
        return [Finding("A-4", root, 0, "not a directory")]
    seen, pinned = [], False
    for name in names:
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        for lineno, line in enumerate(text.splitlines(), 1):
            code = line.split("#", 1)[0]
            if DEP.search(code):
                seen.append((name, lineno))
                if PIN.search(code):
                    pinned = True
    if not seen:
        return [Finding("A-4", root, 0, "no dependency on carla-determinism in "
                        "pyproject.toml, setup.py, setup.cfg or requirements*.txt")]
    if not pinned:
        name, lineno = seen[0]
        return [Finding("A-4", os.path.join(root, name), lineno,
                        "carla-determinism is not pinned to an exact tag (@vX.Y.Z or ==X.Y.Z)")]
    return []


def audit(root):
    root = os.path.abspath(root)
    receivers, launchers, exempt, dep_reason = read_config(root)
    findings = []
    for path in _source_files(root):
        rel = os.path.normpath(os.path.relpath(path, root))
        if rel in exempt:
            continue
        is_launcher = rel in launchers
        for lineno, code in _code_lines(path) or ():
            for m in RAW_CONTROL.finditer(code):
                recv = m.group(1)
                if recv not in receivers and not recv.endswith("carla_determinism"):
                    findings.append(Finding("A-1", rel, lineno,
                                            f"raw {recv}.apply_control( is the fire-and-"
                                            f"forget RPC (D-2); route it through the package"))
            if LAUNCH.search(code) and not is_launcher:
                findings.append(Finding("A-2", rel, lineno,
                                        "CarlaUE4 started outside a declared launcher; "
                                        "the flags will go missing (D-3, D-5)"))
            if SKIP in code:
                findings.append(Finding("A-3", rel, lineno,
                                        f"{SKIP} is an escape hatch; the preflight's value "
                                        f"is that it refuses"))
    if dep_reason is None:
        findings += check_dependency(root)
    return findings


HOOK = f"""#!/bin/sh
{HOOK_MARK}
# Installed by `python3 -m carla_determinism audit --install-hook`. Refuses a commit
# that drives CARLA outside the rules. Allowances go in .carla-determinism-audit.
root="$(git rev-parse --show-toplevel)"
py="${{CARLA_DETERMINISM_PYTHON:-python3}}"
"$py" -m carla_determinism audit "$root" || {{
    echo "commit refused by the carla-determinism audit (above)." >&2
    exit 1
}}
"""


def install_hook(root):
    """Write .git/hooks/pre-commit. Refuses to overwrite a hook that is not ours."""
    hooks = os.path.join(root, ".git", "hooks")
    if not os.path.isdir(hooks):
        raise SystemExit(f"FATAL: {hooks} does not exist; is {root} a git checkout?")
    path = os.path.join(hooks, "pre-commit")
    if os.path.exists(path):
        with open(path) as fh:
            if HOOK_MARK not in fh.read():
                raise SystemExit(f"FATAL: {path} exists and is not ours; merge by hand.")
    with open(path, "w") as fh:
        fh.write(HOOK)
    os.chmod(path, 0o755)
    return path


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="python3 -m carla_determinism audit")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--install-hook", action="store_true",
                    help="write .git/hooks/pre-commit in ROOT and exit")
    args = ap.parse_args(argv)
    if args.install_hook:
        print(f"  wrote {install_hook(os.path.abspath(args.root))}")
        return 0
    findings = audit(args.root)
    if findings:
        print("  CARLA DETERMINISM AUDIT FAILED:")
        for f in findings:
            print(f"    - {f}")
        return 1
    print("  carla-determinism audit OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
