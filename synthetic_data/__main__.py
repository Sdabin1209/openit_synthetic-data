"""python -m synthetic_data run --config <설정.json> [--created-at <UTC Z>]   (run-once)

종료 코드: 0 성공(게시, 이미 게시됨, 할 일 없음), 2 설정 오류, 3 경계 오류(재시도 불가), 75 경계 오류(재시도 가능), 4 import 모드에서 검증 허용치 초과로 게시하지 않음."""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

from boundary_contracts.errors import BoundaryError

import json

from .components import job_output
from .config import ConfigError
from .wiring.import_job import import_from_config
from .wiring.run_job import build_from_config


def _result_line(res) -> str:
    return job_output.run({"kind": "RESULT", "record": asdict(res)})["line"]    # 왜: deploy가 읽는 형식이라 내보내기 전에 계약으로 자기 검사한다(D107)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="synthetic_data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="생성 잡을 한 번 실행한다")
    run.add_argument("--config", required=True, type=Path)
    run.add_argument("--created-at", default=None, help="매니페스트 created_at(UTC Z). 설정보다 우선")
    imp = sub.add_parser("import", help="학습 서버에서 만든 최종 학습 데이터(jsonl 6개)를 검증하고 게시한다(재생성 없음)")
    imp.add_argument("--config", required=True, type=Path)
    imp.add_argument("--created-at", default=None, help="매니페스트 created_at(UTC Z). 설정보다 우선")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "import":
            res = import_from_config(args.config, created_at=args.created_at)
            print(_result_line(res))
            return 4 if res.status == "REJECTED" else 0
        res = build_from_config(args.config, created_at=args.created_at)
    except ConfigError as e:
        print(job_output.run({"kind": "ERROR", "record": {"error": "CONFIG", "message": str(e)}})["line"], file=sys.stderr)
        return 2
    except BoundaryError as e:
        print(json.dumps(e.to_record(), ensure_ascii=False), file=sys.stderr)
        return 75 if e.retryable else 3
    print(_result_line(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
