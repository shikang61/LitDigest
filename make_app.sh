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
    echo "warning: macOS will not let a double-clicked app read files under" >&2
    echo "         Desktop, Documents or Downloads. Move the project elsewhere" >&2
    echo "         (~/LitDigest works) or the app will do nothing when opened." >&2 ;;
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

if [ ! -x "$PROJECT/launch.sh" ]; then
  osascript -e 'display dialog "LitDigest cannot find its project folder.

Expected launch.sh in:
'"$PROJECT"'

Rebuild the app by running make_app.sh in the project folder." buttons {"OK"} default button 1 with title "LitDigest"' >/dev/null 2>&1
  exit 1
fi

mkdir -p "$PROJECT/cache"
exec "$PROJECT/launch.sh" >> "$PROJECT/cache/app.log" 2>&1
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
