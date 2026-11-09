#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
# shellcheck source=/dev/null
source upstream.env
: "${GH_TOKEN:?not set}"
: "${GITHUB_ACTOR:?not set}"
: "${GITHUB_REPOSITORY:?not set}"
: "${GITHUB_STEP_SUMMARY:?not set}"

archive="dist/dograh-$CHART_VERSION.tgz"
# This checksum travels with the archive from the validation job.
sha256sum --check dist/SHA256SUMS
test -f "$archive"
repository="${GITHUB_REPOSITORY,,}/dograh"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT

# Ask for an authenticated registry token, including for the first publication.
# Transport/authentication errors must stop here, not look like an absent chart.
curl --fail --silent --show-error --get \
  --user "$GITHUB_ACTOR:$GH_TOKEN" \
  --data-urlencode service=ghcr.io \
  --data-urlencode "scope=repository:$repository:pull,push" \
  https://ghcr.io/token --output "$work/token.json"
token="$(jq -er '(.token // .access_token) | select(type == "string" and length > 0)' "$work/token.json")"
status="$(curl --silent --show-error \
  --header "Authorization: Bearer $token" \
  --header 'Accept: application/vnd.oci.image.manifest.v1+json' \
  --output "$work/manifest.json" --write-out '%{http_code}' \
  "https://ghcr.io/v2/$repository/manifests/$CHART_VERSION")"
case "$status" in
  200)
    echo "Refusing to replace published chart $repository:$CHART_VERSION" >&2
    exit 1
    ;;
  404)
    # Only explicit OCI 'unknown name/manifest' responses permit a first push.
    jq -e '[.errors[]?.code] | length > 0 and all(. == "MANIFEST_UNKNOWN" or . == "NAME_UNKNOWN")' \
      "$work/manifest.json" >/dev/null
    ;;
  *)
    echo "Registry lookup failed (HTTP $status); publication aborted" >&2
    exit 1
    ;;
esac

printf '%s' "$GH_TOKEN" |
  helm registry login ghcr.io --username "$GITHUB_ACTOR" --password-stdin
helm push "$archive" "oci://ghcr.io/${GITHUB_REPOSITORY,,}" 2>&1 |
  tee "$work/push.txt"
# Markdown backticks below are literal formatting, not command substitutions.
# shellcheck disable=SC2016
{
  printf '## Published chart\n\n'
  printf 'Chart: `oci://ghcr.io/%s`\n\nVersion: `%s`\n\n' "$repository" "$CHART_VERSION"
  printf 'Upstream commit: `%s`\n\n' "$UPSTREAM_COMMIT"
  printf '```text\n%s\n```\n' "$(<"$work/push.txt")"
  printf '\nMake the GHCR package public before anonymous cluster access.\n'
} >>"$GITHUB_STEP_SUMMARY"
