#!/usr/bin/env bash
# -*- coding: utf-8; mode: sh; sh-indentation: 2; indent-tabs-mode: nil; sh-basic-offset: 2; -*-

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
  test "${KEEP_TMP:-0}" = 1 || rm -rf "${_tmp}"
}

generate_requirements() {
  venv="$(pwd)/venv"
  echo "Using virtual environment: $venv"
  ${PYTHON} -m venv "${venv}"
  # shellcheck disable=SC1090
  source ${venv}/bin/activate

  ${venv}/bin/pip install -U pip pip-tools

  ${pip_compile} ${requirements_dir}/requirements*.in --output-file requirements_all.txt

  for file in ${requirements_dir}/requirements*.in; do
    app="$(basename $file .in)"
    echo "Compiling deps for $app"
    ${pip_compile} $file --output-file "$app.txt"
  done
}

main() {
  base_dir=$(pwd)

  _tmp=$(mktemp -d /tmp/tmp.XXXXXX.ansible_base-requirements)

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
    echo "This script generates pinned requirements.txt files from requirements[_*].in"
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

  cd "${_tmp}"
  generate_requirements

  echo "Changing $base_dir to requirements"
  for file in requirements*.txt; do
    sed "s:$base_dir:requirements:" "$file" > "$requirements_dir/$file"
  done

  _cleanup
}

# set EVAL=1 in case you want to source this script
test "${EVAL:-0}" -eq "1" || main "${1:-}"
