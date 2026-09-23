#!/bin/bash
# Builds LitDigest.app for wherever this project currently lives.
#
# The bundle records that absolute path, so rebuild after moving the project.
# Pass a destination to also drop a copy there:  ./make_app.sh ~/Desktop
set -eu
PROJECT="$(cd "$(dirname "$0")" && pwd)"
APP="$PROJECT/LitDigest.app"

case "$PROJECT" in
  "$HOME"/Desktop/*|"$HOME"/Documents/*|"$HOME"/Downloads/*)
    echo "note: macOS will not let a double-clicked app read files under Desktop," >&2
    echo "      Documents or Downloads, so the app will hand off to iTerm (or Terminal)" >&2
    echo "      and a window will flash up. Move the project elsewhere to avoid it." >&2 ;;
esac

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>LitDigest</string>
  <key>CFBundleDisplayName</key><string>LitDigest</string>
  <key>CFBundleIdentifier</key><string>local.litdigest.app</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>LitDigest</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/LitDigest" <<'WRAPPER'
#!/bin/bash
# Finds the project whether this bundle sits inside it or has been copied
# elsewhere (the Desktop, the Dock, /Applications): its own location first,
# then the absolute path recorded when it was built.
BUNDLE="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="$(cd "$BUNDLE/../.." && pwd)"

if [ ! -x "$PROJECT/launch.sh" ] && [ -s "$BUNDLE/Resources/project-path" ]; then
  PROJECT="$(cat "$BUNDLE/Resources/project-path")"
fi

# A blocked path still passes -x; it is opening the file that is refused, so the
# probe has to actually read a byte.
if head -c 1 "$PROJECT/launch.sh" >/dev/null 2>&1; then
  mkdir -p "$PROJECT/cache"
  exec "$PROJECT/launch.sh" >> "$PROJECT/cache/app.log" 2>&1
fi

# The project is somewhere macOS will not let a double-clicked app read --
# Desktop, Documents, Downloads -- so hand the job to a terminal that can, rather
# than failing silently. iTerm first: Terminal is not reliably allowed in either,
# and once refused macOS never asks for it again. osascript fails straight away
# when iTerm is not installed, which falls through to Terminal.
# terminal-launch.sh starts the server detached and returns, so nothing lingers.
TITLE="LitDigest $$"
CMD='\"'"$PROJECT"'/terminal-launch.sh\" \"'"$TITLE"'\"'
if osascript >/dev/null 2>&1 \
     -e 'tell application id "com.googlecode.iterm2" to create window with default profile command "'"$CMD"'"' \
     -e 'tell application id "com.googlecode.iterm2" to activate'; then
  exit 0
fi
if osascript >/dev/null 2>&1 \
     -e 'tell application "Terminal" to do script "'"$CMD"'; exit 0"' \
     -e 'tell application "Terminal" to activate'; then
  exit 0
fi

osascript -e 'display dialog "LitDigest cannot find its project folder.

Expected launch.sh in:
'"$PROJECT"'

Rebuild the app by running make_app.sh in the project folder." buttons {"OK"} default button 1 with title "LitDigest"' >/dev/null 2>&1
exit 1
WRAPPER

chmod +x "$APP/Contents/MacOS/LitDigest"
cp "$PROJECT/assets/icon.icns" "$APP/Contents/Resources/icon.icns"
printf '%s' "$PROJECT" > "$APP/Contents/Resources/project-path"
codesign --force --deep --sign - "$APP" 2>/dev/null || true
touch "$APP"
echo "built $APP  ->  $PROJECT"

if [ $# -ge 1 ]; then
  DEST="${1%/}/LitDigest.app"
  rm -rf "$DEST"
  cp -R "$APP" "$DEST"
  codesign --force --deep --sign - "$DEST" 2>/dev/null || true
  touch "$DEST"
  echo "copied to $DEST"
fi
