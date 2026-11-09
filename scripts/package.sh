#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
# This file is trusted repository configuration, not downloaded upstream code.
# shellcheck source=/dev/null
source upstream.env
if [[ ! "$UPSTREAM_COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo 'UPSTREAM_COMMIT must be a full lowercase Git commit SHA' >&2
  exit 1
fi
if [[ ! "$CHART_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+-upstream\.[0-9a-f]{12}$ ]] ||
  [[ "$CHART_VERSION" != *"-upstream.${UPSTREAM_COMMIT:0:12}" ]]; then
  echo 'CHART_VERSION must be <upstream-version>-upstream.<first-12-commit-characters>' >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
curl --fail --silent --show-error --location --retry 3 \
  "https://codeload.github.com/dograh-hq/dograh/tar.gz/$UPSTREAM_COMMIT" \
  --output "$work/source.tgz"
mkdir "$work/chart"
tar -xzf "$work/source.tgz" -C "$work/chart" --strip-components=3 \
  "dograh-$UPSTREAM_COMMIT/deploy/helm/dograh"
chart="$work/chart/dograh"
# Retain upstream's license in the distributed archive.
tar -xzf "$work/source.tgz" -O "dograh-$UPSTREAM_COMMIT/LICENSE" >"$chart/LICENSE"
printf 'Source: https://github.com/dograh-hq/dograh\nCommit: %s\n' \
  "$UPSTREAM_COMMIT" >"$chart/UPSTREAM.txt"

helm lint "$chart"
mkdir -p dist
helm package "$chart" --version "$CHART_VERSION" --destination dist
archive="dist/dograh-$CHART_VERSION.tgz"
# Render the distributed artifact, not only the source directory.
helm template dograh "$archive" --namespace dograh >"$work/rendered.yaml"
sha256sum "$archive" | tee dist/SHA256SUMS
