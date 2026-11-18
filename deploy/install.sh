#!/usr/bin/env bash
# Resolve the official published release and hand off to its verified installer.
set -euo pipefail
for command in curl python3 sha256sum sudo; do
    command -v "$command" >/dev/null || {
        printf 'Install %s before running PolySia setup.\n' "$command" >&2
        exit 1
    }
done
work=$(mktemp -d)
trap 'rm -r -- "$work"' EXIT
repo=https://github.com/PolySia-Systems/Platform
release_url=$(curl -fsSL --proto '=https' --max-time 30 -o /dev/null \
    -w '%{url_effective}' "$repo/releases/latest")
tag=${release_url##*/}
if [[ "$release_url" != "$repo/releases/tag/$tag" || ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf 'Unable to resolve an official PolySia release.\n' >&2
    exit 1
fi
base="$repo/releases/download/$tag"
curl -fsSL --proto '=https' --max-time 30 -o "$work/manifest.json" "$base/manifest.json"
curl -fsSL --proto '=https' --max-time 30 -o "$work/platform_admin.py" "$base/platform_admin.py"
read -r commit digest < <(python3 - "$work/manifest.json" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
if path.stat().st_size > 65536:
    raise SystemExit("The release manifest exceeds its size limit.")
data = json.loads(path.read_bytes())
commit, digest = data.get("commit", ""), data.get("admin_sha256", "")
if not re.fullmatch(r"[a-f0-9]{40}", commit) or not re.fullmatch(r"[a-f0-9]{64}", digest):
    raise SystemExit("The release manifest does not identify the installer.")
print(commit, digest)
PY
)
(cd "$work"; printf '%s  platform_admin.py\n' "$digest" | sha256sum -c)
if [[ $# -eq 0 ]]; then
    set -- install
fi
sudo python3 "$work/platform_admin.py" "$@" --tag "$tag" --commit "$commit"
