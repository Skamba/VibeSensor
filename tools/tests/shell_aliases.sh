#!/usr/bin/env bash
# Source this file from your shell rc to use VibeSensor test shortcuts.
# Example: echo 'source /home/user/repos/VibeSensor/tools/tests/shell_aliases.sh' >> ~/.bashrc

alias vtest='python3 /home/user/repos/VibeSensor/tools/tests/pytest_progress.py -- -m "not selenium" /home/user/repos/VibeSensor/pi/tests'
alias vtest1='python3 /home/user/repos/VibeSensor/tools/tests/pytest_progress.py -- --maxfail=1 -m "not selenium" /home/user/repos/VibeSensor/pi/tests'
