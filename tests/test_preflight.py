"""The preflight must be able to FAIL. A check that cannot fail is worse than none,
because it is believed. D-9 exists because exactly that happened.
"""
import subprocess
import sys

import carla_determinism as cd
import carla_determinism.preflight


def test_lock_matches_shipped_rules():
    assert cd.check_lock() == [], "RULES.lock does not match RULES.md as shipped"


def test_lock_detects_a_tampered_rule(tmp_path, monkeypatch):
    """Editing a frozen rule must be detected, not silently accepted."""
    original = cd.RULES.read_text()
    try:
        cd.RULES.write_text(original.replace("`-quality-level=Epic`",
                                             "`-quality-level=Low`"))
        problems = cd.check_lock()
        assert problems, "a tampered frozen rule was NOT detected"
        assert "without an amendment" in problems[0]
    finally:
        cd.RULES.write_text(original)
    assert cd.check_lock() == []


def test_missing_server_is_a_violation_not_a_pass():
    """No server on the port must be reported, never treated as compliant."""
    problems = cd.check_server(port=59999, world=None, in_run=False)
    assert any("no CarlaUE4 server" in p for p in problems)


def test_fire_and_forget_control_is_a_violation():
    problems = cd.check_server(port=59999, deterministic_control=False, in_run=False)
    assert any(p.startswith("D-2") for p in problems)


def test_require_deterministic_raises_on_violation():
    try:
        cd.require_deterministic(port=59999, deterministic_control=False)
    except SystemExit as exc:
        assert "PREFLIGHT FAILED" in str(exc)
    else:
        raise AssertionError("require_deterministic did not raise on a violation")


def test_cli_exits_nonzero_on_violation():
    p = subprocess.run([sys.executable, "-m", "carla_determinism",
                        "--port", "59999"], capture_output=True, text=True)
    assert p.returncode == 1
    assert "PREFLIGHT FAILED" in p.stdout


def _fake_argv(extra):
    """A plausible CARLA command line, so the parsing is tested rather than the launcher."""
    return ["/home/x/carla/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping", "CarlaUE4",
            "-carla-rpc-port=3000", "-RenderOffScreen"] + extra


def test_server_present_but_missing_notexturestreaming_is_a_violation(monkeypatch):
    """The branch that matters most: a server that answers RPC perfectly normally and
    is quietly noisier. This is the one a person cannot see."""
    monkeypatch.setattr(cd.preflight, "server_cmdline",
                        lambda port: _fake_argv(["-quality-level=Epic"]))
    problems = cd.check_server(port=3000, in_run=False)
    assert any(p.startswith("D-3") for p in problems), problems
    assert not any(p.startswith("D-5") for p in problems), problems


def test_wrong_quality_level_is_a_violation(monkeypatch):
    monkeypatch.setattr(cd.preflight, "server_cmdline",
                        lambda port: _fake_argv(["-quality-level=Low", "-notexturestreaming"]))
    problems = cd.check_server(port=3000, in_run=False)
    assert any(p.startswith("D-5") and "Low" in p for p in problems), problems


def test_compliant_server_passes(monkeypatch):
    monkeypatch.setattr(cd.preflight, "server_cmdline",
                        lambda port: _fake_argv(["-quality-level=Epic", "-notexturestreaming"]))
    assert cd.check_server(port=3000, deterministic_control=True, in_run=False) == []


def test_port_match_is_exact_not_substring(monkeypatch):
    """A request for port 300 must not match a server on 3000."""
    monkeypatch.setattr(cd.preflight, "carla_processes",
                        lambda: iter([(4242, _fake_argv(["-quality-level=Epic"]))]))
    assert cd.server_cmdline(3000) is not None
    assert cd.server_cmdline(300) is None
    assert cd.preflight.server_pid(300) is None
