"""mlops.pipeline.embedder 디바이스 해석 로직 단위 테스트.

torch import 자체는 함수 내부에서 일어나므로, 테스트는 monkeypatch로
sys.modules['torch']를 가짜 모듈로 대체하거나 builtins.__import__를
가로채는 방식으로 CUDA/MPS/CPU 경로를 결정론적으로 검증한다.
"""

import builtins
import sys
import types

from mlops.pipeline.embedder import _resolve_device


def _fake_torch(*, cuda_available: bool, mps_available: bool) -> types.SimpleNamespace:
    """CUDA/MPS 가용성을 명시적으로 지정한 torch 더미."""
    return types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: cuda_available),
        backends=types.SimpleNamespace(
            mps=types.SimpleNamespace(is_available=lambda: mps_available),
        ),
    )


def test_resolve_device_env_override_wins(monkeypatch):
    """MLOPS_EMBED_DEVICE가 최우선. 'cuda:1' 같은 명시 인덱스도 그대로 반환."""
    monkeypatch.setenv("MLOPS_EMBED_DEVICE", "cuda:1")
    # torch가 어떻든 무시되어야 한다
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=False, mps_available=False))
    assert _resolve_device() == "cuda:1"


def test_resolve_device_returns_cuda_when_available(monkeypatch):
    monkeypatch.delenv("MLOPS_EMBED_DEVICE", raising=False)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=True, mps_available=False))
    assert _resolve_device() == "cuda"


def test_resolve_device_returns_mps_when_only_mps_available(monkeypatch):
    """macOS Apple Silicon 경로."""
    monkeypatch.delenv("MLOPS_EMBED_DEVICE", raising=False)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=False, mps_available=True))
    assert _resolve_device() == "mps"


def test_resolve_device_falls_back_to_cpu_when_no_accelerator(monkeypatch):
    monkeypatch.delenv("MLOPS_EMBED_DEVICE", raising=False)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=False, mps_available=False))
    assert _resolve_device() == "cpu"


def test_resolve_device_handles_missing_torch(monkeypatch):
    """torch 미설치 환경에서 ImportError 발생 시 'cpu'로 fallback."""
    monkeypatch.delenv("MLOPS_EMBED_DEVICE", raising=False)
    # 함수 내부의 `import torch`가 실패하도록 builtins.__import__를 가로챈다.
    # 다른 모듈 import는 그대로 통과.
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch not installed (test simulation)")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    # sys.modules에 캐시된 torch도 제거 (있다면)
    monkeypatch.delitem(sys.modules, "torch", raising=False)
    assert _resolve_device() == "cpu"
