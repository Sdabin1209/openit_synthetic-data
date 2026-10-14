"""python -m synthetic_data run --config <설정.json> [--created-at <UTC Z>]   (run-once)

종료 코드: 0 성공(게시, 이미 게시됨, 할 일 없음), 2 설정 오류, 3 경계 오류(재시도 불가), 75 경계 오류(재시도 가능)."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from boundary_contracts.errors import BoundaryError

from .config import ConfigError
from .job import build_from_config


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="synthetic_data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="생성 잡을 한 번 실행한다")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--created-at", default=None, help="매니페스트 created_at(UTC Z). 설정보다 우선")
    args = ap.parse_args(argv)
    try:
        res = build_from_config(args.config, created_at=args.created_at)
    except ConfigError as e:
        print(json.dumps({"error": "CONFIG", "message": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2
    except BoundaryError as e:
        print(json.dumps(e.to_record(), ensure_ascii=False), file=sys.stderr)
        return 75 if e.retryable else 3
    print(json.dumps(asdict(res), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
