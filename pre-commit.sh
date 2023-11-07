#!/usr/bin/env bash

if [ -z $BASE_IGNORE_SYNTAX ] ; then
    python_files_changed=$(git diff --cached --name-only --diff-filter=AM | grep -E '\.py$' | xargs)
    echo $python_files_changed
    if [ "x$python_files_changed" != "x" ] ; then
        FAILED=0
        for target in check_black check_flake8 ; do
            CHECK_SYNTAX_FILES="${python_files_changed}" make ${target}
            if [ $? != 0 ] ; then
                FAILED=1
            fi
            echo ""
        done
        # We can't run isort on just a file name because it works differently
        make check_isort
        if [ $? != 0 ] ; then
            FAILED=1
        fi
        if [ $FAILED == 1 ] ; then
            exit 1
        fi
    fi
fi

if [ -z $BASE_IGNORE_USER ] ; then
    FAILED=0
    export CHANGED_FILES=$(git diff --cached --name-only --diff-filter=AM)
    echo "Running user pre commit for ${CHANGED_FILES}"
    if [ -d ./pre-commit-user ] ; then
        for SCRIPT in `find ./pre-commit-user -type f` ; do
            if [ -x $SCRIPT ] ; then
                echo "Running user pre-commit hook $SCRIPT"
                $SCRIPT
                if [ $? != 0 ] ; then
                    echo "User test $SCRIPT failed"
                    FAILED=1
                fi
            else
                echo "FIle ${SCRIPT} is not executable"
            fi
        done
    fi
    if [ $FAILED == 1 ] ; then
        echo "One or more user tests failed, see messages above"
        exit 1
    fi
else
    echo "Ignoring user commit scripts due to BASE_IGNORE_ERROR"
fi
