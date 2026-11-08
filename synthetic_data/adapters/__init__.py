"""공개 진입점(ADR 0022). 계약 3.7.0부터 SyntheticJobConfigRun은 factory 문자열을 두지 않고(어댑터는 역할별 HttpClientSettings), 이 영역 코드도 이 이름을 설정에서 읽지 않는다.
ADR 0022 시절 배포 설정이 `synthetic_data.adapters:http_question_reader`·`http_failure_store`를 적었으므로 이름과 호출 시그니처 `(base_url, token_env, timeout=10.0, egress_proxy=None)`은
그대로 둔다(`tests/test_public_factories.py`가 지킨다). 지울지는 ADR 0022를 대체하는 새 ADR로 정한다(아직 정하지 않았다). 구현은 components/link_*에 있고 여기는 이름만 내보낸다."""
from ..components.link_failure_reader import http_failure_store
from ..components.link_question_reader import http_question_reader

__all__ = ["http_question_reader", "http_failure_store"]
