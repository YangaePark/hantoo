#!/bin/sh
set -eu

PROJECT_DIR="${1:-${HANTOO_PROJECT_DIR:-/volume1/docker/hantoo}}"
COMPOSE_URL="https://raw.githubusercontent.com/YangaePark/hantoo/main/deploy/synology/docker-compose.yml"

if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
else
  SUDO=""
fi

run() {
  if [ -n "$SUDO" ]; then
    sudo "$@"
  else
    "$@"
  fi
}

download() {
  url="$1"
  out="$2"
  if command -v curl >/dev/null 2>&1; then
    run curl -fsSL -o "$out" "$url"
  elif command -v wget >/dev/null 2>&1; then
    run wget -O "$out" "$url"
  else
    echo "curl 또는 wget이 필요합니다." >&2
    exit 1
  fi
}

compose() {
  if run docker compose version >/dev/null 2>&1; then
    run docker compose "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    run docker-compose "$@"
  else
    echo "docker compose 또는 docker-compose를 찾을 수 없습니다." >&2
    exit 1
  fi
}

echo "프로젝트 폴더: $PROJECT_DIR"
run mkdir -p "$PROJECT_DIR/state"
download "$COMPOSE_URL" "$PROJECT_DIR/docker-compose.yml"

cd "$PROJECT_DIR"

echo "기존 컨테이너 중지"
compose down || true

echo "최신 코드로 이미지 빌드"
compose build --no-cache

echo "컨테이너 시작"
compose up -d

echo "완료: http://<NAS-IP>:8000"
