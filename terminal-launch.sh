#!/bin/bash
# Run inside a Terminal window by LitDigest.app, for when macOS blocks the app
# from reading the project itself (Desktop, Documents, Downloads).
#
# Starts the server detached and returns. The caller appends "; exit" so the
# window's own shell exits too, which is what actually closes the window --
# AppleScript cannot close a window whose shell is still running.
set -u
TITLE="${1:-LitDigest}"
printf '\033]0;%s\007' "$TITLE"
cd "$(dirname "$0")"

./launch.sh --detach
