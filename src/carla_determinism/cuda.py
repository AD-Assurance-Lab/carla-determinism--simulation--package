"""Model determinism: the preflight pattern, aimed at torch.

A seed is not enough. cuDNN picks convolution kernels by autotuning, several backward
kernels reduce in a data-dependent order, and cuBLAS reductions are repeatable only when
`CUBLAS_WORKSPACE_CONFIG` is set BEFORE the first cuBLAS handle exists. Measured in
`formal-verification--steering--code` (docs/E2_FINDINGS.md): three draws of "seed 0" on
the same data gave fog p99 |err| of 0.1027, 0.1427 and 0.1036, a 1.39x spread, as large
as the spread across six different seeds.

Two calls, same shape as the server preflight:

    cd.pin_torch(seed=0)      # configure: before the first CUDA call in the process
    cd.require_torch()        # assert: before a measurement that runs a model

`torch` is imported inside the functions, like `carla`, so the rest of the package works
without it. Every function takes an optional `torch` argument so a test can hand in a
fake and show that the check fails.
"""
import os
import subprocess

CUBLAS_ENV = "CUBLAS_WORKSPACE_CONFIG"
CUBLAS_DEFAULT = ":4096:8"


def _import_torch(torch=None):
    if torch is not None:
        return torch
    import torch as _torch
    return _torch


def cublas_config_is_late(torch=None):
    """True when CUDA is already initialised and the cuBLAS variable is not set.

    Setting the variable now silently does nothing: the handle was created without it.
    The only fix is to set it before the process starts, or before the first CUDA call.
    """
    if os.environ.get(CUBLAS_ENV):
        return False
    try:
        torch = _import_torch(torch)
        return bool(torch.cuda.is_initialized())
    except Exception:
        return False


def pin_torch(seed=0, warn_only=False, torch=None):
    """Configure torch, numpy and random for repeatable kernels and draws.

    Refuses when the cuBLAS variable would arrive too late, because a pin that
    silently does nothing is worse than none. Returns what was set.
    """
    if cublas_config_is_late(torch):
        raise RuntimeError(
            f"REFUSING to pin torch: CUDA is already initialised and {CUBLAS_ENV} is not "
            f"set.\n    cuBLAS reads it when its first handle is created, so setting it\n"
            f"    now does nothing. Set {CUBLAS_ENV}={CUBLAS_DEFAULT} in the environment,\n"
            f"    or call pin_torch() before the first CUDA call.")
    os.environ.setdefault(CUBLAS_ENV, CUBLAS_DEFAULT)
    torch = _import_torch(torch)

    import random
    random.seed(seed)
    try:
        import numpy
        numpy.random.seed(seed)
    except ImportError:
        pass
    torch.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=warn_only)
    return {
        "seed": seed,
        CUBLAS_ENV: os.environ[CUBLAS_ENV],
        "cudnn_deterministic": True,
        "cudnn_benchmark": False,
        "deterministic_algorithms": True,
        "warn_only": warn_only,
    }


def check_torch(torch=None):
    """Collect model-determinism violations. Empty list means compliant.

    A missing torch is reported, never treated as compliant: the caller asked for a
    model check, and "could not look" is not "looked and found nothing".
    """
    try:
        torch = _import_torch(torch)
    except ImportError:
        return ["torch is not importable; cannot verify model determinism"]
    problems = []
    if not torch.are_deterministic_algorithms_enabled():
        problems.append("M-1: torch.use_deterministic_algorithms is off; several kernels "
                        "reduce in a data-dependent order.")
    if torch.backends.cudnn.benchmark:
        problems.append("M-2: cudnn.benchmark is on; the kernel is chosen by timing, "
                        "not by the input.")
    if not torch.backends.cudnn.deterministic:
        problems.append("M-3: cudnn.deterministic is off.")
    if torch.cuda.is_available() and not os.environ.get(CUBLAS_ENV):
        problems.append(f"M-4: {CUBLAS_ENV} is not set; cuBLAS reductions are not "
                        f"repeatable.")
    return problems


def require_torch(torch=None):
    """Raise unless torch is pinned. Call before a measurement that runs a model."""
    problems = check_torch(torch)
    if problems:
        raise SystemExit(
            "MODEL DETERMINISM PREFLIGHT FAILED -- refusing to produce a measurement.\n"
            "Call carla_determinism.pin_torch(seed) before the first CUDA call.\n  "
            + "\n  ".join(problems))


def gpu_info():
    """(gpu_name, driver_version) from nvidia-smi, or (None, None).

    nvidia-smi rather than torch.cuda.get_device_name: the torch call initialises a CUDA
    context, and a provenance read must not change the state it records.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10)
        if out.returncode != 0 or not out.stdout.strip():
            return None, None
        name, driver = [s.strip() for s in out.stdout.splitlines()[0].split(",", 1)]
        return name, driver
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, None


def torch_provenance(torch=None):
    """What a model ran on, and whether it was pinned. Unknown is None, never False."""
    d = {
        "torch_version": None, "cuda_version": None, "cudnn_version": None,
        "cuda_available": None, "deterministic_algorithms": None,
        "cudnn_benchmark": None, "cudnn_deterministic": None,
        CUBLAS_ENV: os.environ.get(CUBLAS_ENV),
        "gpu_name": None, "driver_version": None,
    }
    d["gpu_name"], d["driver_version"] = gpu_info()
    try:
        torch = _import_torch(torch)
    except ImportError:
        return d
    try:
        d["torch_version"] = str(torch.__version__)
        d["cuda_version"] = torch.version.cuda
        d["cudnn_version"] = torch.backends.cudnn.version()
        d["cuda_available"] = bool(torch.cuda.is_available())
        d["deterministic_algorithms"] = bool(torch.are_deterministic_algorithms_enabled())
        d["cudnn_benchmark"] = bool(torch.backends.cudnn.benchmark)
        d["cudnn_deterministic"] = bool(torch.backends.cudnn.deterministic)
    except Exception:
        pass
    return d
