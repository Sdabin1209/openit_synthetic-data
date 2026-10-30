"""공개 진입점: 잡 설정의 adapters.*.factory가 가리키는 이름(ADR 0022). 계약 SyntheticJobConfigRun이 factory를 `module:function` 문자열로 정하고
배포 설정(deploy e2e)이 `synthetic_data.adapters:http_question_reader`·`http_failure_store`를 적는다. 이 이름과 호출 시그니처 `(base_url, token_env, timeout=10.0)`은
이 영역의 공개 약속이라 지우거나 옮기지 않는다(`tests/test_public_factories.py`가 지킨다). 구현은 components/link_*에 있고 여기는 이름만 내보낸다."""
from ..components.link_failure_reader import http_failure_store
from ..components.link_question_reader import http_question_reader

__all__ = ["http_question_reader", "http_failure_store"]
