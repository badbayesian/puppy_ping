#!/usr/bin/env bash
set -euo pipefail

export BUILD_CONTEXT="."
export BUILD_TARGET="dev"

docker compose up -d --build
