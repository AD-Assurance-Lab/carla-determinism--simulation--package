"""The audit must fail on each pattern, and pass a clean repository."""
import json
import os
import subprocess
import sys
import textwrap

import pytest

import carla_determinism as cd


def _repo(tmp_path, files, config=None):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text))
    if config is not None:
        (tmp_path / cd.audit.CONFIG).write_text(config)
    return str(tmp_path)


CLEAN = {
    "pyproject.toml": '''
        [project]
        name = "study"
        dependencies = [
          "carla-determinism @ git+https://github.com/x/y@v1.3.0",
        ]
    ''',
    "src/env.py": '''
        """A docstring may say vehicle.apply_control() without being a call."""
        import carla_determinism as cd
        def apply_control(vehicle, control):
            # a comment: vehicle.apply_control() is the race
            cd.apply_control(vehicle, control)
    ''',
    "scripts/carla_launch.sh": '''
        #!/bin/sh
        python3 -m carla_determinism launch --port 3000
    ''',
}


def _codes(findings):
    return sorted(f.code for f in findings)


def test_clean_repo_passes(tmp_path):
    assert cd.audit_repo(_repo(tmp_path, CLEAN)) == []


def test_raw_apply_control_is_found(tmp_path):
    files = dict(CLEAN)
    files["scripts/drive.py"] = "vehicle.apply_control(ctrl)\n"
    f = cd.audit_repo(_repo(tmp_path, files))
    assert _codes(f) == ["A-1"] and f[0].line == 1 and "drive.py" in f[0].path


def test_allowed_receiver_is_not_found(tmp_path):
    files = dict(CLEAN)
    files["scripts/drive.py"] = "env.apply_control(vehicle, ctrl)\n"
    assert _codes(cd.audit_repo(_repo(tmp_path, files))) == ["A-1"]
    assert cd.audit_repo(_repo(tmp_path, files, config="allow-receiver env\n")) == []


def test_inline_allowance_skips_one_line_only(tmp_path):
    files = dict(CLEAN)
    files["scripts/drive.py"] = ("vehicle.apply_control(c)   # carla-determinism: allow, replay\n"
                                 "vehicle.apply_control(c)\n")
    f = cd.audit_repo(_repo(tmp_path, files))
    assert _codes(f) == ["A-1"] and f[0].line == 2


def test_exempt_file_is_skipped_entirely(tmp_path):
    files = dict(CLEAN)
    files["tests/fixtures.py"] = 'vehicle.apply_control(c)\nx = "./CarlaUE4.sh"\ny = "CARLA_SKIP_PREFLIGHT"\n'
    assert len(cd.audit_repo(_repo(tmp_path, files))) == 3
    assert cd.audit_repo(_repo(tmp_path, files, config="exempt tests/fixtures.py\n")) == []


def test_hand_launch_is_found_and_a_declared_launcher_is_not(tmp_path):
    files = dict(CLEAN)
    files["scripts/old_start.sh"] = "cd ~/carla && ./CarlaUE4.sh -carla-rpc-port=3000\n"
    f = cd.audit_repo(_repo(tmp_path, files))
    assert _codes(f) == ["A-2"] and "old_start.sh" in f[0].path
    assert cd.audit_repo(_repo(tmp_path, files, config="launcher scripts/old_start.sh\n")) == []


def test_binary_launch_from_python_is_found(tmp_path):
    files = dict(CLEAN)
    files["tools/proc.py"] = 'subprocess.Popen(["CarlaUE4-Linux-Shipping", "-RenderOffScreen"])\n'
    assert _codes(cd.audit_repo(_repo(tmp_path, files))) == ["A-2"]


def test_escape_hatch_is_found(tmp_path):
    files = dict(CLEAN)
    files["src/env.py"] += '\nif not os.environ.get("CARLA_SKIP_PREFLIGHT"):\n    pass\n'
    assert _codes(cd.audit_repo(_repo(tmp_path, files))) == ["A-3"]


def test_missing_dependency_is_found(tmp_path):
    files = dict(CLEAN)
    files["pyproject.toml"] = '[project]\nname = "study"\ndependencies = []\n'
    f = cd.audit_repo(_repo(tmp_path, files))
    assert _codes(f) == ["A-4"] and "no dependency" in f[0].text


def test_unpinned_dependency_is_found(tmp_path):
    files = dict(CLEAN)
    files["pyproject.toml"] = ('[project]\nname = "study"\ndependencies = ['
                               '"carla-determinism @ git+https://github.com/x/y@main"]\n')
    f = cd.audit_repo(_repo(tmp_path, files))
    assert _codes(f) == ["A-4"] and "not pinned" in f[0].text


def test_exact_version_pin_in_requirements_passes(tmp_path):
    files = dict(CLEAN)
    del files["pyproject.toml"]
    files["requirements.txt"] = "carla-determinism==1.3.0\n"
    assert cd.audit_repo(_repo(tmp_path, files)) == []


def test_exempt_dependency_needs_a_reason(tmp_path):
    files = dict(CLEAN)
    files["pyproject.toml"] = '[project]\nname = "study"\ndependencies = []\n'
    assert _codes(cd.audit_repo(_repo(tmp_path, files))) == ["A-4"]
    assert _codes(cd.audit_repo(_repo(tmp_path, files, config="exempt-dependency\n"))) == ["A-4"]
    assert cd.audit_repo(_repo(tmp_path, files,
                               config="exempt-dependency runs in ../other/.venv\n")) == []


def test_venv_and_git_are_not_scanned(tmp_path):
    files = dict(CLEAN)
    files[".venv/lib/x.py"] = "vehicle.apply_control(c)\n"
    files[".git/hooks/x.sh"] = "./CarlaUE4.sh\n"
    assert cd.audit_repo(_repo(tmp_path, files)) == []


def test_this_package_audits_clean():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert cd.audit_repo(here) == []


def test_cli_exits_one_on_a_finding(tmp_path):
    files = dict(CLEAN)
    files["scripts/drive.py"] = "vehicle.apply_control(ctrl)\n"
    root = _repo(tmp_path, files)
    p = subprocess.run([sys.executable, "-m", "carla_determinism", "audit", root],
                       capture_output=True, text=True)
    assert p.returncode == 1 and "A-1" in p.stdout


def test_install_hook_writes_and_refuses_to_clobber(tmp_path):
    root = _repo(tmp_path, CLEAN)
    os.makedirs(os.path.join(root, ".git", "hooks"))
    path = cd.audit.install_hook(root)
    assert os.access(path, os.X_OK) and cd.audit.HOOK_MARK in open(path).read()
    cd.audit.install_hook(root)                       # ours: overwrite is fine
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\necho someone else\n")
    with pytest.raises(SystemExit, match="not ours"):
        cd.audit.install_hook(root)


def test_installed_hook_uses_the_configured_interpreter(tmp_path):
    """The hook must find an interpreter that has the package, and refuse otherwise."""
    root = _repo(tmp_path, CLEAN, config=f"python {os.path.relpath(sys.executable, tmp_path)}\n")
    os.makedirs(os.path.join(root, ".git", "hooks"))
    subprocess.run(["git", "init", "-q", root], check=True)
    hook = cd.audit.install_hook(root)
    env = {k: v for k, v in os.environ.items() if k != "CARLA_DETERMINISM_PYTHON"}
    # A PATH with git, sed and head but NO python3, so only the configured one can work.
    import shutil
    bin_dir = tmp_path / "bin"; bin_dir.mkdir()
    for tool in ("git", "sed", "head"):
        os.symlink(shutil.which(tool), bin_dir / tool)
    env["PATH"] = str(bin_dir)
    ok = subprocess.run(["/bin/sh", hook], cwd=root, env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    (tmp_path / cd.audit.CONFIG).write_text("")      # nothing configured, nothing on PATH
    refused = subprocess.run(["/bin/sh", hook], cwd=root, env=env, capture_output=True, text=True)
    assert refused.returncode == 1 and "no interpreter" in refused.stderr


def _hook(command):
    p = subprocess.run([sys.executable, "-m", "carla_determinism", "claude-hook"],
                       input=json.dumps({"tool_input": {"command": command}}),
                       capture_output=True, text=True)
    return p.returncode, p.stderr


def test_claude_hook_blocks_a_hand_launch():
    rc, err = _hook("cd ~/carla && ./CarlaUE4.sh -carla-rpc-port=3000 -RenderOffScreen")
    assert rc == 2 and "refusing" in err


def test_claude_hook_allows_the_package_launcher_and_lookups():
    assert _hook("python3 -m carla_determinism launch --port 3000 --map Town04")[0] == 0
    assert _hook("bash scripts/simulator/carla_launch.sh")[0] == 0
    assert _hook("pgrep -af CarlaUE4-Linux-Shipping")[0] == 0
    assert _hook("ls -la")[0] == 0
