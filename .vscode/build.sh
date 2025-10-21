#!/usr/bin/env bash
set -euo pipefail

CLI_LOCATION="$(pwd)/cli"

# Calendar version (UTC): yyyy.mm.dd.HHMM
BASE_VERSION="$(date -u +%Y.%m.%d.%H%M)"

# Short git commit id (works in GitHub Actions; may fall back locally)
SHORT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo "local")"

# Final version with commit id
NEW_VERSION="${BASE_VERSION}-${SHORT_SHA}"
echo "New version: $NEW_VERSION (base: $BASE_VERSION, commit: $SHORT_SHA)"

# Update package.json
tmpfile="$(mktemp)"
jq --arg v "$NEW_VERSION" '.version = $v' package.json > "$tmpfile"
mv "$tmpfile" package.json
echo "version in package.json updated to $NEW_VERSION"

echo "Building plugin in $(pwd)"
sudo "$CLI_LOCATION/decky" plugin build "$(pwd)"

# Expose version to GitHub Actions (so workflow can tag/release)
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "version=$NEW_VERSION" >> "$GITHUB_OUTPUT"
fi

echo "Build of version $NEW_VERSION complete."