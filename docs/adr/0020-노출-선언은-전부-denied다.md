# ADR 0020: 노출 선언(`io.openit.exposure`)은 전 경로 denied다

상태: 채택 (2026-10-30). 계약 `Exposure`(boundary-contracts v2.6.0), OPEN_GAPS U47.

## 맥락
deploy의 Caddyfile이 영역 API 경로·메서드·역할을 직접 알았다(구조 규칙 1 위반). 계약은 영역이 자기 이미지에 노출 표를 라벨로 선언하게 했다.

## 결정
- 리포 루트 `deploy-exposure.json`이 정본이고 `scripts/build-image.sh`가 `Exposure`로 검증해 라벨 `io.openit.exposure`에 싣는다.
- 내용은 경로 `/v1/datasets`, `/v1/datasets/*`, `/healthz`, `/readyz` 전부 `auth.kind=denied`(모든 메서드).

## 왜
- dataset-store는 서비스 사이 내부망(compose 네트워크 `datasets`, internal)에서만 읽힌다. 읽기는 model-lab, 쓰기는 synthetic-data 잡이고 키오스크·직원 경로에서 닿지 않는다(deploy ADR 0032를 compose.yaml 주석으로 확인, 그 ADR 문서는 읽지 않았다).
- deploy `config/Caddyfile`에서 dataset·synthetic·`/v1/datasets`를 찾았으나 없었다(grep). 코드의 라우트(`/v1/datasets`, 그 하위, `/healthz`, `/readyz`)가 표와 같고 `tests/test_build_image.py`가 일치를 본다. 어긋남은 없다.
- 계약은 노출하지 않는 경로를 denied로 적게 한다.

## 검토한 대안
- 표를 비움: 스키마가 `routes` 최소 1개를 요구한다.
- 읽기·쓰기 역할을 account로 선언: 게이트웨이로 노출한다는 뜻이 되어 실제 배치와 다르다.

## 결과
얻는 것: deploy가 라벨만 읽고 이 서비스 경로를 짐작하지 않는다. 감수하는 것: 노출이 필요해지면 표와 deploy를 같이 바꿔야 한다.

## 되돌리는 조건
dataset-store를 게이트웨이로 노출하기로 하면 새 ADR로 대체한다.
