"""A10(표준성 점검 2026-10-29): ALREADY_PUBLISHED 판정이 import와 run에서 같아야 한다.
기대값: 계약 I2의 멱등 규칙(같은 입력은 같은 결과)과 docs/design.md 10절·CR-005(version 지정 여부와 무관하게 digest가 같으면 이미 게시됨)."""
from __future__ import annotations

import pytest

from boundary_contracts.errors import BoundaryError
from conftest import make_cfg_raw, run
from synthetic_data.wiring.import_job import run_import
from synthetic_data.components.dataset_store import MemoryDatasetStore
from test_import import cfg_for, write_input


def test_run_with_pinned_version_and_other_created_at_is_already_published(tmp_path, validators):
    store = MemoryDatasetStore(validators.contract_version)
    raw = make_cfg_raw(tmp_path, version="v-pinned")
    _, first = run(raw, store, validators)
    assert first.status == "PUBLISHED"
    raw2 = make_cfg_raw(tmp_path, version="v-pinned", created_at="2026-10-16T00:00:00Z")
    _, again = run(raw2, store, validators)
    assert again.status == "ALREADY_PUBLISHED" and again.content_hash == first.content_hash


def test_import_and_run_agree_on_pinned_version_rerun(tmp_path, validators):
    write_input(tmp_path / "in")
    store = MemoryDatasetStore(validators.contract_version)
    a = run_import(cfg_for(tmp_path, version="v-pin"), store=store, survey=validators)
    b = run_import(cfg_for(tmp_path, version="v-pin", created_at="2026-10-28T00:00:00Z"), store=store, survey=validators)
    assert (a.status, b.status) == ("PUBLISHED", "ALREADY_PUBLISHED")
