"""저장소 주입: 계획의 store 항목으로 파일·메모리·HTTP 구현 중 하나를 만든다. 잡(run)과 게시기(import)가 같은 것을 쓴다."""
from __future__ import annotations

from pathlib import Path

from ..components import link_dataset_publish
from ..components.dataset_store import FileDatasetStore
from ..config import ConfigError


def build_store(store: dict, survey):
    """kind: file(root) | http. file은 로컬 개발용이고, 운영에서 dataset-store(I2 서버)로 게시할 때는 http다(D100, CR-D26)."""
    if store["kind"] == "http":
        try:
            return link_dataset_publish.build(store["http"])
        except link_dataset_publish.TokenError as e:
            raise ConfigError(str(e)) from None
    # 왜 else 분기가 없나(D117): kind 는 RunPlan·ImportPlan 스키마 enum(file|http)이 plans.py 를 지나며 이미 막는다. 코드 안에서 다시 거부하지 않는다(tests/test_contract_schemas.py)
    return FileDatasetStore(Path(store["root"]), survey.contract_version)
