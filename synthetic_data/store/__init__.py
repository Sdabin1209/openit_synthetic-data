"""I2 DatasetStore 구현: 파일 기반과 메모리. 같은 적합성 시험을 통과한다."""
from .file_store import FileDatasetStore
from .memory_store import MemoryDatasetStore

__all__ = ["FileDatasetStore", "MemoryDatasetStore"]
