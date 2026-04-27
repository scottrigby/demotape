#!/usr/bin/env bash
# Bump showtape's version in every place that pins it. Designed to keep the
# tracked artifacts (pyproject.toml + feature manifest, the two CI compares)
# in lockstep with documentation and the dev/test-consumer devcontainers.
#
# Updates:
#   - pyproject.toml                                     [project].version
#   - feature/showtape/devcontainer-feature.json         "version"
#   - .devcontainer/devcontainer.json                    OCI feature ref tag
#   - _test-consumer/.devcontainer/devcontainer.json     OCI feature ref tag (if present)
#   - README.md                                          OCI feature ref tag + `vX.Y.Z` examples
#
# Not touched: src/showtape/__init__.py reads via importlib.metadata.
#
# Usage:  scripts/bump-version.sh 0.3.1
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <new-version>   e.g. 0.3.1" >&2
  exit 2
fi
NEW="$1"

if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]]; then
  echo "error: '$NEW' doesn't look like a semver version" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 - "$NEW" "$ROOT" <<'PY'
import json, re, sys
from pathlib import Path

new, root = sys.argv[1], Path(sys.argv[2])

# 1. pyproject.toml — [project].version (only the first occurrence)
p = root / "pyproject.toml"
text = p.read_text()
text, n = re.subn(r'^version = "[^"]*"', f'version = "{new}"',
                  text, count=1, flags=re.MULTILINE)
assert n == 1, f"failed to bump {p}"
p.write_text(text)
print(f"  {p.relative_to(root)} → version = \"{new}\"")

# 2. devcontainer-feature.json — top-level "version"
p = root / "feature/showtape/devcontainer-feature.json"
data = json.loads(p.read_text())
data["version"] = new
p.write_text(json.dumps(data, indent=2) + "\n")
print(f"  {p.relative_to(root)} → \"version\": \"{new}\"")

# 3 + 4. devcontainer.json files — OCI tag in feature ref
oci_re = re.compile(r"ghcr\.io/scottrigby/showtape/showtape:\d+\.\d+\.\d+(?:-[\w.-]+)?")
for rel in [".devcontainer/devcontainer.json",
            "_test-consumer/.devcontainer/devcontainer.json"]:
    p = root / rel
    if not p.exists():
        continue
    text = p.read_text()
    new_text, n = oci_re.subn(f"ghcr.io/scottrigby/showtape/showtape:{new}", text)
    if n:
        p.write_text(new_text)
        print(f"  {rel} → :{new} ({n} ref{'s' if n > 1 else ''})")

# 5. README.md — OCI tag in feature ref AND git tag examples (vX.Y.Z)
p = root / "README.md"
text = p.read_text()
new_text, n_oci = oci_re.subn(f"ghcr.io/scottrigby/showtape/showtape:{new}", text)
new_text, n_tag = re.subn(r"v\d+\.\d+\.\d+(?:-[\w.-]+)?", f"v{new}", new_text)
if n_oci or n_tag:
    p.write_text(new_text)
    print(f"  README.md → :{new} ({n_oci} OCI ref{'s' if n_oci > 1 else ''}) "
          f"+ v{new} ({n_tag} git-tag mention{'s' if n_tag > 1 else ''})")
PY

echo
echo "Sanity check — every pinned mention now reads $NEW:"
"$ROOT/scripts/check-version-sync.sh" "$NEW" || {
  echo "error: bump produced inconsistent state — investigate manually" >&2
  exit 1
}

cat <<EOF

Next:
  git diff
  git commit -am "Bump to v$NEW"
  git push origin main      # CI tags v$NEW + publishes OCI feature
EOF
