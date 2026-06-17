#!/usr/bin/env bash
# Verify agent-runner network lockdown (Spec §7.2, Issue #8).
# Run from the project root with the Compose stack up:
#   bash scripts/verify-egress-lockdown.sh
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

pass=0
fail=0

check() {
    local description="$1"
    local expect_success="$2"
    shift 2
    local output exit_code

    output=$(docker compose exec -T agent-runner "$@" 2>&1) && exit_code=0 || exit_code=$?

    if [ "$expect_success" = "true" ] && [ "$exit_code" -eq 0 ]; then
        echo -e "  ${GREEN}PASS${NC}: $description"
        ((pass++))
    elif [ "$expect_success" = "false" ] && [ "$exit_code" -ne 0 ]; then
        echo -e "  ${GREEN}PASS${NC}: $description (blocked as expected)"
        ((pass++))
    else
        echo -e "  ${RED}FAIL${NC}: $description"
        echo "       Output: $output"
        ((fail++))
    fi
}

echo "=== Agent-runner egress lockdown verification ==="
echo ""

echo "1. Proxy environment variables"
check "HTTP_PROXY is set" true \
    sh -c 'test -n "$HTTP_PROXY"'
check "HTTPS_PROXY is set" true \
    sh -c 'test -n "$HTTPS_PROXY"'

echo ""
echo "2. Allowlisted domains (should succeed via proxy)"
check "github.com reachable via proxy" true \
    sh -c 'python3 -c "import urllib.request; urllib.request.urlopen(\"https://github.com\", timeout=10)"'
check "api.github.com reachable via proxy" true \
    sh -c 'python3 -c "import urllib.request; urllib.request.urlopen(\"https://api.github.com\", timeout=10)"'
check "pypi.org reachable via proxy" true \
    sh -c 'python3 -c "import urllib.request; urllib.request.urlopen(\"https://pypi.org\", timeout=10)"'

echo ""
echo "3. Non-allowlisted domains (should be blocked by Squid)"
check "example.com blocked by proxy" false \
    sh -c 'python3 -c "import urllib.request; urllib.request.urlopen(\"https://example.com\", timeout=10)"'
check "google.com blocked by proxy" false \
    sh -c 'python3 -c "import urllib.request; urllib.request.urlopen(\"https://google.com\", timeout=10)"'

echo ""
echo "4. Direct egress bypass (should fail — no external route)"
check "Direct curl bypassing proxy is blocked" false \
    sh -c 'unset HTTP_PROXY HTTPS_PROXY; python3 -c "import urllib.request; urllib.request.urlopen(\"https://example.com\", timeout=10)"'

echo ""
echo "5. Filesystem boundary"
check "/workspace is mounted" true \
    sh -c 'test -d /workspace'
check "Cannot write outside workspace (read-only root)" false \
    sh -c 'touch /opt/testfile'

echo ""
echo "6. Other services retain normal internet (orchestrator-api)"
api_check=$(docker compose exec -T orchestrator-api \
    python3 -c "import urllib.request; urllib.request.urlopen('https://example.com', timeout=10); print('OK')" 2>&1) && api_exit=0 || api_exit=$?
if [ "$api_exit" -eq 0 ]; then
    echo -e "  ${GREEN}PASS${NC}: orchestrator-api has normal internet access"
    ((pass++))
else
    echo -e "  ${RED}FAIL${NC}: orchestrator-api should have normal internet access"
    echo "       Output: $api_check"
    ((fail++))
fi

echo ""
echo "=== Results: $pass passed, $fail failed ==="
[ "$fail" -eq 0 ] && exit 0 || exit 1
