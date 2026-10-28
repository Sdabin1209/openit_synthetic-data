#!/usr/bin/env bash
# 왜: 이 영역의 환경 준비는 이 파일이 정본이다. 새 머신으로 옮길 때 README·런북마다 설치법이
#     달라 형제 폴더 editable 설치 같은 어긋남이 났으므로 한 곳으로 모았다.
#     버전·태그는 requirements.lock이 정본이라 여기에 적지 않는다.
set -euo pipefail

# 어느 폴더에서 실행해도 리포 루트 기준(이 파일 위치의 상위)으로 동작한다.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

[ -f requirements.lock ] || { echo "setup-env: requirements.lock이 없다" >&2; exit 1; }
command -v python3 >/dev/null || { echo "setup-env: python3가 없다" >&2; exit 1; }

# 멱등: 있으면 재사용한다. 깨진 .venv(pip 없음)는 사유를 내고 멈춘다(자동 삭제하지 않는다).
if [ ! -d .venv ]; then
  python3 -m venv .venv || { echo "setup-env: venv 생성 실패(python3-venv 필요할 수 있음)" >&2; exit 1; }
fi
[ -x .venv/bin/python ] || { echo "setup-env: .venv가 깨졌다. .venv를 지우고 다시 실행" >&2; exit 1; }

# pytest는 잠금 파일에 고정돼 있다. -e . 는 이 리포(synthetic_data)를 개발 설치한다.
install() { .venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock -e .; }

# 왜 1회 재시도: 일시적 네트워크 실패(git 태그 내려받기 포함)를 흡수하되, 계속되면 숨기지 않고 실패한다.
if ! install; then
  echo "setup-env: 설치 실패, 5초 뒤 한 번 재시도" >&2
  sleep 5
  install || { echo "setup-env: 설치 실패(네트워크 또는 git SSH 접근 확인: requirements.lock의 태그 설치)" >&2; exit 1; }
fi

echo "setup-env: 완료. 시험: .venv/bin/python -m pytest -q"
