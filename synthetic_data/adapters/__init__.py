"""설정 값 호환 별칭. 계약 SyntheticJobConfigRun의 adapters.*.factory가 `synthetic_data.adapters:http_question_reader`를 가리키는 배포 설정이 있다(deploy e2e).
코드는 components/link_*에 있고 여기는 이름만 다시 내보낸다(변경 요청 docs/change-requests/CR-S-001: factory 값이 영역 내부 모듈 경로를 가리키는 문제)."""
from ..components.link_failure_reader import http_failure_store
from ..components.link_question_reader import http_question_reader

__all__ = ["http_question_reader", "http_failure_store"]
