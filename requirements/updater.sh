#!/usr/bin/env bash
set -ue

PYTHON=python3.11

for FILE in requirements.in requirements_all.txt ; do
	if [ ! -f ${FILE} ] ; then
		touch ${FILE}
	fi
done
requirements_dir="$(readlink -f .)"
requirements_txt="$(readlink -f ./requirements_all.txt)"
pip_compile="pip-compile --no-header --quiet -r --allow-unsafe"

_cleanup() {
  cd /
  test "${KEEP_TMP:-0}" = 1 || rm -rf "${_tmp}"
}

generate_requirements() {
  venv="`pwd`/venv"
  echo $venv
  ${PYTHON} -m venv "${venv}"
  # shellcheck disable=SC1090
  source ${venv}/bin/activate

  ${venv}/bin/python -m pip install -U 'pip' pip-tools

  ${pip_compile} $(ls ${requirements_dir}/requirements*.in | xargs) --output-file requirements_all.txt
}

main() {
  base_dir=$(pwd)

  _tmp=$(${PYTHON} -c "import tempfile; print(tempfile.mkdtemp(suffix='.aap-gw-requirements', dir='/tmp'))")

  trap _cleanup INT TERM EXIT

  case $1 in
    "run")
      NEEDS_HELP=0
    ;;
    "upgrade")
      NEEDS_HELP=0
      pip_compile="${pip_compile} --upgrade"
    ;;
    "help")
      NEEDS_HELP=1
    ;;
    *)
      echo ""
      echo "ERROR: Parameter $1 not valid"
      echo ""
      NEEDS_HELP=1
    ;;
  esac 

  if [[ "$NEEDS_HELP" == "1" ]] ; then
    echo "This script generates requirements_all.txt from requirements[_*].in"
    echo ""
    echo "Usage: $0 [run|upgrade]"
    echo ""
    echo "Commands:"
    echo "help      Print this message"
    echo "run       Run the process only upgrading pinned libraries from requirements[_*].in"
    echo "upgrade   Upgrade all libraries to latest while respecting pinnings"
    echo ""
    exit
  fi

  cp -vf ${requirements_txt} "${_tmp}"
  cd "${_tmp}"

  generate_requirements

  echo "Changing $base_dir to requirements"
  cat requirements_all.txt | sed "s:$base_dir:requirements:" > "${requirements_txt}"

  _cleanup
}

# set EVAL=1 in case you want to source this script
test "${EVAL:-0}" -eq "1" || main "${1:-}"

