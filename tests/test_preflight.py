"""The preflight must be able to FAIL. A check that cannot fail is worse than none,
because it is believed. D-9 exists because exactly that happened.
"""
import subprocess
import sys

import carla_determinism as cd


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
    p = subprocess.run([sys.executable, "-m", "carla_determinism.preflight",
                        "--port", "59999"], capture_output=True, text=True)
    assert p.returncode == 1
    assert "PREFLIGHT FAILED" in p.stdout
