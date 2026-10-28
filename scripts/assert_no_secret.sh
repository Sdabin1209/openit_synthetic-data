#!/bin/sh
# 표준 입력에 비밀 값(인자)이 있으면 실패(종료 코드 1). `! cmd | grep` 형태는 set -e에서 실패를 놓치므로 if로 분기한다.
for s in "$@"; do
  if [ -z "$s" ]; then echo "빈 비밀 인자" >&2; exit 2; fi
done
IN=$(cat)
for s in "$@"; do
  if printf '%s\n' "$IN" | grep -q -F -e "$s"; then
    echo "비밀 값이 로그에 있다" >&2   # 값은 출력하지 않는다
    exit 1
  fi
done
exit 0
