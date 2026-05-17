#!/usr/bin/env bash
# Build a macOS .pkg installer for Verdikt.
#
# Prerequisites:
#   pip install pyinstaller
#   Xcode Command Line Tools (for pkgbuild / productbuild)
#
# Usage:
#   cd distribution
#   bash installers/macos/build.sh
#   # Output: Verdikt-<VERSION>.pkg

set -euo pipefail

DIST_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="${VERSION:-1.0}"
BUILD_DIR="$DIST_DIR/build"

cd "$DIST_DIR"
mkdir -p "$BUILD_DIR"

echo "→ Freezing tray launcher…"
pyinstaller --onefile --windowed --name VerdiktTray \
    --distpath "$BUILD_DIR/dist" \
    tray/__main__.py

echo "→ Freezing setup wizard…"
pyinstaller --onefile --windowed --name VerdiktWizard \
    --distpath "$BUILD_DIR/dist" \
    wizard/__main__.py

# Assemble .app bundle for the tray (LSUIElement hides from Dock)
echo "→ Assembling VerdiktTray.app…"
APP="$BUILD_DIR/VerdiktTray.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD_DIR/dist/VerdiktTray" "$APP/Contents/MacOS/"
[[ -f "assets/icon_256.png" ]] && cp "assets/icon_256.png" "$APP/Contents/Resources/AppIcon.png"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>    <string>VerdiktTray</string>
    <key>CFBundleIdentifier</key>   <string>com.verdikt.tray</string>
    <key>CFBundleName</key>         <string>Verdikt</string>
    <key>CFBundleVersion</key>      <string>${VERSION}</string>
    <key>CFBundleIconFile</key>     <string>AppIcon</string>
    <key>LSUIElement</key>          <true/>
</dict>
</plist>
PLIST

# Payload layout (installed to /Applications/Verdikt/)
echo "→ Staging payload…"
PAYLOAD="$BUILD_DIR/payload"
mkdir -p "$PAYLOAD/Applications/Verdikt"
cp -r "$APP"                    "$PAYLOAD/Applications/Verdikt/"
cp "$BUILD_DIR/dist/VerdiktWizard" "$PAYLOAD/Applications/Verdikt/"
cp compose.*.yml                "$PAYLOAD/Applications/Verdikt/"
[[ -d assets ]] && cp -r assets "$PAYLOAD/Applications/Verdikt/"

# Build component package
echo "→ pkgbuild…"
pkgbuild \
    --root "$PAYLOAD" \
    --identifier com.verdikt.app \
    --version "$VERSION" \
    --install-location / \
    "$BUILD_DIR/component.pkg"

# Build distributable installer
echo "→ productbuild…"
productbuild \
    --distribution installers/macos/distribution.xml \
    --package-path "$BUILD_DIR" \
    "$BUILD_DIR/Verdikt-${VERSION}.pkg"

echo "✅  $BUILD_DIR/Verdikt-${VERSION}.pkg"
