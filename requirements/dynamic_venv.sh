#!/usr/bin/env bash

function cd() {
  command cd "$@" || return

  VIRTUAL_PATH=~/virtualenvs
  CURRENT_PYTHON=`which python | sed 's:/bin/python::' | sed 's:.*/::'`
  PATHS=`echo $PWD | sed 's:/::' | sed 's:/:\n:g' | tac`

  for path in $PATHS ; do
    if [ -d "${VIRTUAL_PATH}/${path}" ] ; then
      if [ "${CURRENT_PYTHON}" != "${path}" ]; then
        if [ -z ${CURRENT_PYTHON} ] ; then:
          deactivate
        fi
        source ${VIRTUAL_PATH}/${path}
      fi
    fi
  done
}
