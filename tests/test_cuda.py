"""The model checks must REFUSE. A fake torch shows each branch fails; a real torch,
when one is installed, shows the pin is accepted and the un-pin is caught."""
import os
import types

import pytest

import carla_determinism as cd


def _fake_torch(det=True, bench=False, cudnn_det=True, cuda=False, initialised=False):
    """The surface the checks touch, and nothing more."""
    t = types.SimpleNamespace()
    t.__version__ = "0.0.0-fake"
    t.version = types.SimpleNamespace(cuda="0.0")
    t.backends = types.SimpleNamespace(cudnn=types.SimpleNamespace(
        benchmark=bench, deterministic=cudnn_det, version=lambda: 0))
    t.cuda = types.SimpleNamespace(is_available=lambda: cuda,
                                   is_initialized=lambda: initialised)
    state = {"det": det}
    t.are_deterministic_algorithms_enabled = lambda: state["det"]

    def use_det(flag, warn_only=False):
        state["det"] = flag
    t.use_deterministic_algorithms = use_det
    t.manual_seed = lambda s: None
    return t


def test_pinned_fake_passes(monkeypatch):
    monkeypatch.setenv(cd.cuda.CUBLAS_ENV, ":4096:8")
    assert cd.check_torch(_fake_torch(cuda=True)) == []


def test_unpinned_algorithms_is_a_violation(monkeypatch):
    monkeypatch.setenv(cd.cuda.CUBLAS_ENV, ":4096:8")
    problems = cd.check_torch(_fake_torch(det=False))
    assert any(p.startswith("M-1") for p in problems), problems


def test_cudnn_benchmark_is_a_violation(monkeypatch):
    monkeypatch.setenv(cd.cuda.CUBLAS_ENV, ":4096:8")
    assert any(p.startswith("M-2") for p in cd.check_torch(_fake_torch(bench=True)))


def test_cudnn_nondeterministic_is_a_violation(monkeypatch):
    monkeypatch.setenv(cd.cuda.CUBLAS_ENV, ":4096:8")
    assert any(p.startswith("M-3") for p in cd.check_torch(_fake_torch(cudnn_det=False)))


def test_missing_cublas_config_with_cuda_is_a_violation(monkeypatch):
    monkeypatch.delenv(cd.cuda.CUBLAS_ENV, raising=False)
    assert any(p.startswith("M-4") for p in cd.check_torch(_fake_torch(cuda=True)))


def test_require_torch_raises(monkeypatch):
    monkeypatch.setenv(cd.cuda.CUBLAS_ENV, ":4096:8")
    with pytest.raises(SystemExit, match="MODEL DETERMINISM PREFLIGHT FAILED"):
        cd.require_torch(_fake_torch(det=False))


def test_pin_refuses_when_cublas_config_is_too_late(monkeypatch):
    """CUDA already up and the variable unset: setting it now does nothing, so refuse."""
    monkeypatch.delenv(cd.cuda.CUBLAS_ENV, raising=False)
    with pytest.raises(RuntimeError, match="REFUSING"):
        cd.pin_torch(seed=0, torch=_fake_torch(initialised=True))


def test_pin_sets_everything_on_a_fake(monkeypatch):
    monkeypatch.delenv(cd.cuda.CUBLAS_ENV, raising=False)
    t = _fake_torch(det=False, bench=True, cudnn_det=False, cuda=True)
    cd.pin_torch(seed=7, torch=t)
    assert os.environ[cd.cuda.CUBLAS_ENV] == cd.cuda.CUBLAS_DEFAULT
    assert cd.check_torch(t) == []


def test_missing_torch_is_reported_not_passed(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_torch(name, *a, **k):
        if name == "torch":
            raise ImportError("no torch here")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_torch)
    monkeypatch.delitem(__import__("sys").modules, "torch", raising=False)
    problems = cd.check_torch()
    assert problems and "not importable" in problems[0]


def test_real_torch_pin_and_unpin(monkeypatch):
    """With a real torch installed: the pin passes, and undoing one setting is caught."""
    torch = pytest.importorskip("torch")
    if torch.cuda.is_initialized() and not os.environ.get(cd.cuda.CUBLAS_ENV):
        pytest.skip("CUDA already initialised in this process without the cuBLAS variable")
    saved = (torch.are_deterministic_algorithms_enabled(),
             torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic)
    try:
        cd.pin_torch(seed=0)
        assert cd.check_torch() == []
        torch.backends.cudnn.benchmark = True
        assert any(p.startswith("M-2") for p in cd.check_torch())
    finally:
        torch.use_deterministic_algorithms(saved[0])
        torch.backends.cudnn.benchmark = saved[1]
        torch.backends.cudnn.deterministic = saved[2]


def test_provenance_records_unknown_as_none():
    stamp = cd.provenance(port=59999, world=None, deterministic_control=None)
    assert stamp["package_version"] == cd.__version__
    assert stamp["lock_ok"] is True
    assert stamp["server_argv"] is None
    assert stamp["server_age_s"] is None
    assert stamp["deterministic_control"] is None
    assert stamp["world_settings"] is None
    assert "torch" in stamp and "gpu_name" in stamp["torch"]


def test_provenance_records_the_server_when_present(monkeypatch):
    argv = ["/x/CarlaUE4-Linux-Shipping", "CarlaUE4", "-carla-rpc-port=3000",
            "-notexturestreaming", "-quality-level=Epic"]
    monkeypatch.setattr(cd.preflight, "carla_processes", lambda: iter([(1, argv)]))
    monkeypatch.setattr(cd.hygiene, "server_age_s", lambda port: 12.0)
    monkeypatch.setattr(cd.provenance_module, "server_age_s", lambda port: 12.0)
    stamp = cd.provenance(port=3000, deterministic_control=True)
    assert stamp["server_argv"] == argv
    assert stamp["server_age_s"] == 12.0
    assert stamp["deterministic_control"] is True
