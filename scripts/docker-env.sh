# docker 를 부르는 스크립트가 source 해서 쓰는 환경 한 곳(docker_env_setup). 사용자 전역 ~/.docker 설정(Windows 자격 도우미 credsStore)에 기대지 않게 한다.
# 왜: 이 영역이 받는 기반 이미지는 공개 이미지를 digest 로 고정한 것이라 레지스트리 자격이 필요 없다. 전역 설정의 자격 도우미가 응답하지 않으면(Docker Desktop vsock 110)
#     `docker build` 가 "error getting credentials" 로 실패했다. 표준 환경 변수 DOCKER_CONFIG 로 리포 안 빈 설정({})을 주면 도우미를 부르지 않는다(deploy D10(5), kiosk-frontend scripts/docker-env.mjs 와 같은 규칙).
# 규칙: DOCKER_CONFIG 가 이미 주어지면 그대로 쓴다(deploy 가 인증이 필요한 레지스트리용 설정을 넘기는 경우). 없을 때만 build/docker-config 의 빈 설정을 쓴다.
#       DOCKER_HOST 가 없고 현재 docker 컨텍스트의 엔드포인트가 기본 소켓이 아니면 그 엔드포인트를 DOCKER_HOST 로 넘긴다(설정을 바꾸면 컨텍스트가 안 보이기 때문). 엔드포인트는 docker CLI 에게 묻는다.
#       사용자 ~/.docker 는 읽지도 고치지도 않는다.
docker_env_setup() {
  # 왜 $PWD: 부르는 스크립트가 모두 리포 루트로 cd 한 뒤 source 한다. POSIX sh(smoke_service.sh 는 #!/bin/sh)에서도 돌도록 bash 전용 기능을 쓰지 않는다.
  root="$PWD"
  if [ -z "${DOCKER_HOST:-}" ]; then
    host="$("${DOCKER:-docker}" context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)"
    case "$host" in
      ""|unix:///var/run/docker.sock) ;;
      unix://*|tcp://*|ssh://*|npipe://*) export DOCKER_HOST="$host" ;;
    esac
  fi
  if [ -z "${DOCKER_CONFIG:-}" ]; then
    mkdir -p "$root/build/docker-config"
    printf '{}\n' >"$root/build/docker-config/config.json"
    export DOCKER_CONFIG="$root/build/docker-config"
  fi
}
