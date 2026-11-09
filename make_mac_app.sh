#!/bin/bash
# Build "SQL Helper.app", a double-clickable launcher, inside this project folder.
# Run once after cloning:  ./make_mac_app.sh
#
# The app is a tiny AppleScript applet (built with macOS's own osacompile) that
# runs ./run.sh in the background. It's an applet rather than a plain shell-script
# bundle because macOS only shows its "allow access to your Documents folder"
# prompt for a proper app. A script-only bundle is silently blocked if the
# project lives in Documents, Desktop or Downloads.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$PROJECT_DIR/SQL Helper.app"

if [ "$(uname)" != "Darwin" ]; then
  echo "This builds a macOS app. On other systems, run ./run.sh instead." >&2
  exit 1
fi

rm -rf "$APP"
/usr/bin/osacompile -o "$APP" <<'APPLESCRIPT'
-- SQL Helper launcher: runs run.sh from the folder this app sits in.
set appPath to POSIX path of (path to me)
set projectDir to do shell script "dirname " & quoted form of appPath
set runScript to projectDir & "/run.sh"
try
	do shell script "test -f " & quoted form of runScript
on error
	display dialog "SQL Helper.app must stay inside the SQL Helper project folder (next to run.sh). To launch it from the Dock, drag it onto the Dock instead of moving it." with title "SQL Helper" buttons {"OK"} default button 1 with icon caution
	return
end try
-- Run in the background so this launcher can quit straight away.
do shell script "SQL_HELPER_GUI=1 /bin/bash " & quoted form of runScript & " >/dev/null 2>&1 &"
APPLESCRIPT

# Use our icon instead of the default AppleScript one. Changing the bundle
# invalidates the ad-hoc signature osacompile made, so sign it again (ad hoc,
# no developer account needed).
ICON="$PROJECT_DIR/sql_helper/assets/icon.icns"
if [ -f "$ICON" ]; then
  cp "$ICON" "$APP/Contents/Resources/applet.icns"
  /usr/bin/codesign --force --sign - "$APP" >/dev/null 2>&1 || true
  touch "$APP"   # nudge Finder to refresh the icon
fi

echo "Built: $APP"
echo "Double-click it in Finder, or drag it onto the Dock. Keep it in this folder."
