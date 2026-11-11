"""ROCm execution policy. Training math is shared with the formal Mac source."""
import os
from functools import lru_cache


def resolve_device():
    # CPU/MPS are permitted only in explicit local formula verification.
    requested = os.environ.get('R5_ACCELERATOR', 'rocm')
    if os.environ.get('R5_AMD_VALIDATION') == '1' and requested in ('cpu', 'mps'):
        return requested
    if requested != 'rocm':
        raise RuntimeError('The AMD workbench requires R5_ACCELERATOR=rocm')
    return 'cuda'  # PyTorch exposes HIP using its cuda namespace.


@lru_cache(maxsize=1)
def available():
    if os.environ.get('R5_GPU_TRAINING', '1').lower() in ('0', 'false', 'off'):
        return False
    import torch
    device = resolve_device()
    if device == 'cpu':
        return True
    if device == 'mps':
        return torch.backends.mps.is_available()
    enabled = bool(torch.version.hip and torch.cuda.is_available())
    if enabled:
        # Each fitter is a fresh process; server-only flags do not propagate
        # through PyTorch state. Apply the same FP32 policy in every process.
        torch.set_float32_matmul_precision('highest')
    return enabled


def synchronize():
    import torch
    if resolve_device() == 'cuda':
        torch.cuda.synchronize()
    elif resolve_device() == 'mps':
        torch.mps.synchronize()


def empty_cache():
    import torch
    if resolve_device() == 'cuda':
        torch.cuda.empty_cache()
    elif resolve_device() == 'mps':
        torch.mps.empty_cache()


def configure():
    if not available():
        raise RuntimeError('ROCm GPU unavailable; floating training cannot fall back to CPU')
    import torch
    torch.set_num_threads(10)
    if resolve_device() == 'cuda':
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision('highest')


def policy():
    import torch
    enabled = available()
    return dict(requested='rocm', available=enabled, device=resolve_device(),
        backend='AMD ROCm/PyTorch' if enabled else 'ROCm unavailable', cpu_threads=10,
        torch=torch.__version__, hip=torch.version.hip,
        gpu_name=torch.cuda.get_device_name(0) if enabled and resolve_device() == 'cuda' else None,
        native_integer_backend='CPU float32/FMA emulation; 10 threads; exact integer acceptance')
