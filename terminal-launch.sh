#!/bin/bash
# Run inside an iTerm or Terminal window by LitDigest.app, for when macOS blocks
# the app from reading the project itself (Desktop, Documents, Downloads).
#
# Starts the server detached and returns. In iTerm this script is the session's
# command, so returning ends the session and closes the window. In Terminal it
# runs inside a shell, so the caller appends "; exit" to make that shell exit too,
# which is what actually closes the window -- AppleScript cannot close a window
# whose shell is still running.
set -u
TITLE="${1:-LitDigest}"
printf '\033]0;%s\007' "$TITLE"
cd "$(dirname "$0")"

./launch.sh --detach
