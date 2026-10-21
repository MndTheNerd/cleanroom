#!/bin/sh
# Isolation probe. Prints one JSON object per check and exits 1 if any expectation fails.
# Env from the host:
#   CLEANROOM_CANARIES  newline-separated strings taken from upstream files; none may exist in this container
set -u
fail=0
emit() { # name expected actual detail
  ok=false; [ "$2" = "$3" ] && ok=true
  [ "$ok" = true ] || fail=1
  printf '{"check":"%s","expected":"%s","actual":"%s","ok":%s,"detail":"%s"}\n' "$1" "$2" "$3" "$ok" "$(printf '%s' "$4" | tr '"\n' "' " | cut -c1-200)"
}

# 1. Mounts: the only bind mount from the host must be /work (plus Docker's resolv/hosts/hostname files).
extra=$(awk '{print $5}' /proc/self/mountinfo | grep -vE '^(/|/work|/proc.*|/sys.*|/dev.*|/etc/(resolv.conf|hosts|hostname)|/tmp|/home/node)$' | tr '\n' ' ')
emit only_work_mounted "" "$extra" "unexpected mount points: $extra"

# 2. Upstream content must not be anywhere in the container filesystem.
found=""
if [ -n "${CLEANROOM_CANARIES:-}" ]; then
  printf '%s\n' "$CLEANROOM_CANARIES" > /tmp/canaries
  hit=$(grep -rIlF -f /tmp/canaries / --exclude-dir=proc --exclude-dir=sys --exclude-dir=dev --exclude-dir=tmp 2>/dev/null | head -5 | tr '\n' ' ')
  found="$hit"
  rm -f /tmp/canaries
  emit upstream_not_readable "" "$found" "files containing upstream canary strings: $found"
else
  emit upstream_not_readable "canaries" "none-provided" "host passed no canary strings"
fi

# 3. Network: GitHub must be unreachable, directly and through the proxy.
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 https://github.com 2>/dev/null); [ -z "$code" ] && code=000
emit github_via_proxy_blocked "000" "$code" "proxy should refuse CONNECT to github.com"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 --noproxy '*' https://github.com 2>/dev/null); [ -z "$code" ] && code=000
emit github_direct_blocked "000" "$code" "no route to the internet without the proxy"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 --noproxy '*' https://140.82.112.3 2>/dev/null); [ -z "$code" ] && code=000
emit direct_ip_blocked "000" "$code" "raw IP egress"
if getent hosts github.com >/dev/null 2>&1; then dns=resolved; else dns=failed; fi
emit external_dns_blocked "failed" "$dns" "external DNS resolution"

# 4. The model API must be reachable through the proxy (any HTTP status proves the tunnel works).
#    Retry briefly: the proxy may still be starting.
code=000
for _ in 1 2 3 4 5 6; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 https://api.anthropic.com/v1/models 2>/dev/null); [ -z "$code" ] && code=000
  [ "$code" != "000" ] && break
  sleep 3
done
if [ "$code" = "000" ]; then api=unreachable; else api=reachable; fi
emit model_api_reachable "reachable" "$api" "HTTP $code"

# 5. Identity / privileges.
emit non_root "1000" "$(id -u)" "uid"
if touch /usr/local/probe 2>/dev/null; then ro=writable; else ro=readonly; fi
emit rootfs_readonly "readonly" "$ro" "root filesystem"

exit $fail
