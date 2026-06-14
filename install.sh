#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${HOME}/.local/bin"
target="${bin_dir}/agent-lifeboat"
venv_dir="${repo_dir}/.venv"

mkdir -p "${bin_dir}"

if [[ ! -x "${venv_dir}/bin/python" ]]; then
  python3 -m venv "${venv_dir}"
fi

if ! "${venv_dir}/bin/python" -c "import textual" >/dev/null 2>&1; then
  "${venv_dir}/bin/python" -m pip install "textual>=0.80"
fi

version="$("${venv_dir}/bin/python" -c "from codex_lifeboat import __version__; print(__version__)")"

cat > "${target}" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${repo_dir}\${PYTHONPATH:+:\${PYTHONPATH}}"
exec "${venv_dir}/bin/python" -m codex_lifeboat.tui "\$@"
EOF
chmod +x "${target}"

rm -f "${bin_dir}/codex-lifeboat"

echo "Installed ${target} (${version})"
echo "Make sure ${bin_dir} is on your PATH."
echo "Run: agent-lifeboat"
