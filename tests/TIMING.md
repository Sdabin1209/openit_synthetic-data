# 시험의 시간 사용 (U422)

시험 중 실제 시간을 기다리거나 재서 판정하는 곳이 0이다. 처리: 지움 / 1 우리 코드의 시간(시계 주입, ADR 0023) / 2 라이브러리 안의 시간(넘기는 값 확인 + 즉시 실패 가짜) / 3 속도 측정(시간 단언 지움) / 매달림 감시(`HANG_GUARD_SECONDS`, tests/conftest.py).

## u422-timing-tests.txt의 이 영역 시험
| 시험 | 목적 한 줄 | 처리 | 바뀐 시험 |
|---|---|---|---|
| test_import.py::test_pii_patterns_are_fast_on_adversarial_text | 개인정보 패턴이 입력을 폭주(ReDoS)시키지 않는다 | 3 (시간 단언 지움, 방어 장치 확인) | `test_pii_patterns_have_bounded_non_nested_repeats`: 모든 반복 수량자에 상한, 중첩 반복 없음, 입력 길이 상한이 있고 악성 입력이 끝난다 |
| test_service_server_properties.py::test_in_flight_request_finishes_when_server_is_shutting_down | 종료 신호 뒤에도 진행 중 요청은 끝까지 응답한다 | 1 (드레인 한도가 주입된 시계로 잰다) | 같은 이름. 시작·해제 Event와 멈춘 가짜 시계로 순서를 맞춘다(sleep 없음) |
| (추가) test_drain_gives_up_when_the_grace_passes_with_a_request_that_never_ends 외 2건 | 드레인 한도가 지나면 포기하고, 요청이 먼저 끝나면 정상 종료한다 | 1 (가짜 시계 + 최소 가짜 채널) | `_drain(poll)`로 분리해 시험 |
| test_service_server_properties.py::test_sigterm_stops_the_service_process_cleanly | 진입점이 SIGTERM에 서버를 멈추고 드레인 설정을 넘긴다 | 2 (실제 프로세스·신호를 지움) | `test_sigterm_handler_stops_the_server_loop`: 등록된 처리기를 직접 불러 정지 사건과 `DATASET_STORE_DRAIN_GRACE` 값을 확인. 프로세스 기동·왕복은 smoke_service.sh의 몫 |

## 그 밖에 시간에 기대던 시험(같은 기준으로 처리)
| 시험 | 목적 한 줄 | 처리 | 바뀐 시험 |
|---|---|---|---|
| test_slow_header_clients_do_not_block_other_requests, test_idle_connection_is_closed_after_timeout, test_server_recovers_after_connection_flood | waitress가 느린·유휴·폭주 연결을 다룬다(라이브러리) | 지움 + 2 (값 확인) | `test_waitress_receives_the_configured_limits`, `test_defaults_are_the_documented_starting_values` |
| test_oversized_body_is_refused_and_server_keeps_working, test_service.py::test_size_limits의 413 부분 | 본문 상한 413(openit_link.Route가 낸다, 소켓에서 큰 본문을 보내면 연결 재설정 경쟁) | 지움 + 2 (값 확인) | `test_publish_route_uses_the_service_body_limit`, `test_size_limits`(Route.max_body·stream_body) |
| test_service.py::test_auth_failure_window_expires_and_frees_memory, ::test_auth_failure_throttle_blocks_even_valid_token | 인증 실패 횟수 제한의 창이 지나면 풀리고 메모리가 비워진다(우리 코드) | 1 (가짜 시계 `FakeClock`을 `Service(clock=)`에 주입, `advance`로 흘림) | 같은 이름, sleep 없음 |
| test_service_fuzz.py::test_fuzz_paths_headers_methods | 잘못된 요청에도 서버가 죽지 않는다 | 실제 대기 제거 | 요청을 다 보낸 뒤 쓰기 쪽을 닫아(`SHUT_WR`) 짧은 본문에서 서버가 시간 초과를 기다리지 않게 함(60초 → 4초) |
| test_service.py::_raw (고정 sleep) | 원시 소켓 응답 읽기 | 지움 | recv가 응답까지 기다림 |
| tests/ref_server.py `delay` | 쓰는 시험이 없는 sleep | 지움 | |

## 매달림 감시 (판정 아님, 코드가 진짜로 멈췄을 때만 닿는다)
`HANG_GUARD_SECONDS = 300`(tests/conftest.py)을 쓰는 곳: urlopen·소켓·HTTP 연결 마감(test_service, test_service_auth_status, test_service_fuzz), Event.wait·join(test_service_server_properties), 하위 프로세스 실행(test_setup_env, test_build_image).

## 정적 확인
시험 코드의 `time.monotonic/perf_counter/time.time/time.sleep`과 숫자 timeout은 0이다(`tests/test_timing_table.py`가 막는다). 컴포넌트 코드가 시간을 직접 읽는 곳도 0이다(`synthetic_data/components`에 `import time` 없음, 같은 시험이 확인). 실제 시간을 읽는 곳은 wiring(`wiring/service.py`의 `clock=time.monotonic`, 잡의 `created_at` 기본값)뿐이다.
