#!/usr/bin/env bash
set -euo pipefail

CLI_LOCATION="$(pwd)/cli"

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  # Use committed version
  PKG_VERSION="$(jq -r '.version' package.json)"
  echo "Using committed version: $PKG_VERSION"
  NEW_VERSION="$PKG_VERSION"
else
  # Local dev build - generate version
  BASE_VERSION="$(date -u +%Y.%m.%d.%H%M)"
  SHORT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "local")"
  NEW_VERSION="${BASE_VERSION}-${SHORT_SHA}"
  echo "Local dev version: $NEW_VERSION"
  tmpfile="$(mktemp)"
  jq --arg v "$NEW_VERSION" '.version = $v' package.json > "$tmpfile"
  mv "$tmpfile" package.json
  echo "version in package.json updated to $NEW_VERSION"
fi

echo "Building plugin in $(pwd)"
sudo "$CLI_LOCATION/decky" plugin build "$(pwd)"

# Expose version to GitHub Actions (so workflow can tag/release)
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "version=$NEW_VERSION" >> "$GITHUB_OUTPUT"
fi

echo "Build of version $NEW_VERSION complete."