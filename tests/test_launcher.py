"""The launcher must refuse, and its own command line must satisfy the preflight."""
import pytest

import carla_determinism as cd


def _as_proc_argv(argv):
    """What /proc shows for a server started with `argv`: the binary, then the flags."""
    return ["/home/x/carla/CarlaUE4/Binaries/Linux/CarlaUE4-Linux-Shipping", "CarlaUE4"] + argv[1:]


def test_launch_argv_satisfies_the_preflight(monkeypatch):
    argv = cd.launch_argv(3000)
    monkeypatch.setattr(cd.preflight, "server_cmdline", lambda port: _as_proc_argv(argv))
    assert cd.check_server(3000, deterministic_control=True, in_run=False) == []


def test_launch_argv_windowed_still_satisfies_the_preflight(monkeypatch):
    argv = cd.launch_argv(3000, windowed=True, res=(800, 600))
    assert "-windowed" in argv and "-ResX=800" in argv and "-RenderOffScreen" not in argv
    monkeypatch.setattr(cd.preflight, "server_cmdline", lambda port: _as_proc_argv(argv))
    assert cd.check_server(3000, in_run=False) == []


def test_extra_cannot_override_a_rule_flag():
    with pytest.raises(ValueError, match="rule flag"):
        cd.launch_argv(3000, extra=["-quality-level=Low"])
    with pytest.raises(ValueError, match="rule flag"):
        cd.launch_argv(3000, extra=["-carla-rpc-port=2000"])


def test_extra_flags_are_kept():
    assert "-benchmark" in cd.launch_argv(3000, extra=["-benchmark"])


def test_launch_refuses_an_occupied_port(monkeypatch):
    held = _as_proc_argv(cd.launch_argv(3000))
    monkeypatch.setattr(cd.preflight, "server_cmdline", lambda port: held)
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: True)
    with pytest.raises(SystemExit, match="already serves"):
        cd.launch(3000, carla_root="/nonexistent")


def test_launch_refuses_a_bound_port_with_no_carla_process(monkeypatch):
    """Something else on the port is still something else; do not launch into it."""
    monkeypatch.setattr(cd.preflight, "server_cmdline", lambda port: None)
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: True)
    with pytest.raises(SystemExit, match="already serves"):
        cd.launch(3000, carla_root="/nonexistent")


def test_launch_refuses_windowed_without_a_display(monkeypatch):
    monkeypatch.setattr(cd.preflight, "server_cmdline", lambda port: None)
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: False)
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(SystemExit, match="no DISPLAY"):
        cd.launch(3000, carla_root="/nonexistent", windowed=True)


def test_launch_refuses_a_server_that_came_up_wrong(monkeypatch, tmp_path):
    """The branch that matters: the process started, answered, and lacks a flag."""
    bad = ["/x/CarlaUE4-Linux-Shipping", "CarlaUE4", "-carla-rpc-port=3000",
           "-quality-level=Epic", "-RenderOffScreen"]
    state = {"started": False}

    def start(*a, **k):
        state["started"] = True
        return 4242
    monkeypatch.setattr(cd.preflight, "server_cmdline",
                        lambda port: bad if state["started"] else None)
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: state["started"])
    monkeypatch.setattr(cd.launcher, "start_server", start)
    monkeypatch.setattr(cd.launcher, "wait_ready", lambda *a, **k: "Town04")
    import io
    with pytest.raises(SystemExit, match="violates the rules"):
        cd.launch(3000, carla_root="/x", log_path=str(tmp_path / "c.log"), out=io.StringIO())


def test_launch_reports_a_good_server(monkeypatch, tmp_path):
    """No server before start_server; the right one after. The final argv is the real one."""
    good = _as_proc_argv(cd.launch_argv(3000))
    state = {"started": False}

    def start(*a, **k):
        state["started"] = True
        return 4242
    monkeypatch.setattr(cd.preflight, "server_cmdline",
                        lambda port: good if state["started"] else None)
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: state["started"])
    monkeypatch.setattr(cd.launcher, "start_server", start)
    monkeypatch.setattr(cd.launcher, "wait_ready", lambda *a, **k: "Town04")
    import io
    info = cd.launch(3000, carla_root="/x", log_path=str(tmp_path / "c.log"), out=io.StringIO())
    assert info["pid"] == 4242 and info["map"] == "Town04" and info["argv"] == good


def test_launch_does_not_time_out_silently(monkeypatch, tmp_path):
    monkeypatch.setattr(cd.preflight, "server_cmdline", lambda port: None)
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: False)
    monkeypatch.setattr(cd.launcher, "start_server", lambda *a, **k: 4242)

    def never(*a, **k):
        raise TimeoutError("CARLA not ready on 3000 after 1s. Last error: refused")
    monkeypatch.setattr(cd.launcher, "wait_ready", never)
    import io
    with pytest.raises(SystemExit, match="not ready"):
        cd.launch(3000, carla_root="/x", log_path=str(tmp_path / "c.log"), out=io.StringIO())


def test_stop_is_a_noop_when_nothing_serves(monkeypatch):
    monkeypatch.setattr(cd.preflight, "server_pid", lambda port: None)
    monkeypatch.setattr(cd.launcher, "_wrapper_pids", lambda port: [])
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: False)
    assert cd.stop(3000) is True


def test_stop_signals_only_the_pids_on_this_port(monkeypatch):
    sent = []
    monkeypatch.setattr(cd.preflight, "server_pid", lambda port: 111 if sent == [] else None)
    monkeypatch.setattr(cd.launcher, "_wrapper_pids", lambda port: [110])
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: False)
    monkeypatch.setattr(cd.launcher.os, "kill", lambda pid, sig: sent.append((pid, sig)))
    assert cd.stop(3000, grace_s=1.0) is True
    assert sorted(p for p, _ in sent) == [110, 111]
    assert all(s == cd.launcher.signal.SIGTERM for _, s in sent), "SIGKILL was not needed"


def test_stop_raises_when_the_port_stays_held(monkeypatch):
    monkeypatch.setattr(cd.preflight, "server_pid", lambda port: None)
    monkeypatch.setattr(cd.launcher, "_wrapper_pids", lambda port: [])
    monkeypatch.setattr(cd.preflight, "port_listening", lambda port: True)
    with pytest.raises(RuntimeError, match="still held"):
        cd.stop(3000, grace_s=0.6)
