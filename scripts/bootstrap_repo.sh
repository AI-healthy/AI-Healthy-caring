#!/usr/bin/env bash
set -euo pipefail
REMOTE_URL="${REMOTE_URL:-git@github.com:AI-healthy/AI-Healthy-caring.git}"
echo "仓库已经初始化；请直接 clone：${REMOTE_URL}"
echo 'git clone "$REMOTE_URL"'
