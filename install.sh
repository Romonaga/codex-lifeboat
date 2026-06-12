#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${HOME}/.local/bin"
target="${bin_dir}/codex-lifeboat"

mkdir -p "${bin_dir}"
cp "${repo_dir}/codex_lifeboat.py" "${target}"
chmod +x "${target}"

echo "Installed ${target}"
echo "Make sure ${bin_dir} is on your PATH."
echo "Run: codex-lifeboat"
