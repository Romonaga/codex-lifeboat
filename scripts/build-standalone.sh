#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv_dir="${repo_dir}/.venv"

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  python3 -m venv "${venv_dir}"
fi

"${venv_dir}/bin/python" -m pip install -e "${repo_dir}[standalone]"
"${venv_dir}/bin/python" -m codex_lifeboat.build

version="$("${venv_dir}/bin/python" -c "from codex_lifeboat import __version__; print(__version__)")"
echo "Built ${repo_dir}/dist/agent-lifeboat"
echo "Built ${repo_dir}/dist/agent-lifeboat-${version}"
echo "Wrote ${repo_dir}/dist/build-info.json"
