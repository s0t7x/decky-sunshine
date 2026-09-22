#!/usr/bin/env bash
#
# Branch coverage for the Python backend, with a ratchet.
#
# pyproject.toml carries the coverage reached so far as fail_under. A run that
# does better raises it; a run that does worse fails. Why branch coverage and
# why a ratchet at all: tests/README.md.
#
#   tools/coverage.sh              # measure, report, raise the floor
#   tools/coverage.sh --no-raise   # measure and report only
#
# CI does not run this script - it calls coverage directly and never raises
# the floor, because a CI job that edits the repository is a surprise.
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${COVERAGE_VENV:-.venv-tests}"
DATA=".coverage-data"
RAISE=1
case "${1:-}" in
  "")          ;;
  --no-raise)  RAISE=0 ;;
  *)           echo "usage: $0 [--no-raise]" >&2; exit 64 ;;
esac

if [ ! -x "$VENV/bin/python" ]; then
  # A venv rather than a system install: SteamOS and most current distros mark
  # their Python as externally managed (PEP 668), so pip refuses outside one.
  echo "Creating $VENV ..."
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
fi

# Every run, not just on creation: a venv that is missing one plugin still
# looks fine. pytest reports an unknown config option as a warning and carries
# on - which is how the suite once ran with its timeout silently disabled.
"$VENV/bin/pip" install --quiet -r requirements-test.txt

rm -rf "$DATA"
mkdir -p "$DATA"
export COVERAGE_FILE="$DATA/.coverage"

"$VENV/bin/coverage" run -m pytest -q > "$DATA/tests.log" || {
  echo "Tests failed - coverage numbers would be meaningless. See $DATA/tests.log" >&2
  exit 1
}

"$VENV/bin/coverage" report
"$VENV/bin/coverage" xml -o "$DATA/coverage.xml" --quiet
"$VENV/bin/coverage" json -o "$DATA/coverage.json" --quiet

"$VENV/bin/python" - "$DATA/coverage.json" "$RAISE" <<'PY'
import json, math, re, sys

totals = json.load(open(sys.argv[1]))["totals"]
branches, covered = totals["num_branches"], totals["covered_branches"]
reached = totals["percent_covered"]

config = open("pyproject.toml").read()
floor = float(re.search(r"^fail_under = ([\d.]+)$", config, re.M).group(1))

print(f"\nBranch coverage: {covered}/{branches} ({100 * covered / branches:.0f}%)   "
      f"partially taken: {totals['num_partial_branches']}")
print(f"Combined (the ratchet's number): {reached:.2f}%, floor {floor:.2f}%")

if reached + 1e-9 < floor:
    sys.exit(f"\nCoverage fell below the floor. Something stopped being checked.")

# Only ever upwards, and only on a deliberate local run - CI passes --no-raise,
# because a CI job that edits the repo is a surprise nobody wants.
#
# Rounded DOWN, not to nearest: a floor of round(99.7867, 2) = 99.79 is higher
# than the run that produced it, so the very next run of the unchanged suite
# fails its own ratchet.
new_floor = math.floor(reached * 100) / 100
if sys.argv[2] == "1" and new_floor > floor:
    new = f"{new_floor:.2f}".rstrip("0").rstrip(".")
    open("pyproject.toml", "w").write(
        re.sub(r"^fail_under = [\d.]+$", f"fail_under = {new}", config, count=1, flags=re.M))
    print(f"Raised the floor to {new}% - commit pyproject.toml with your tests.")
PY
