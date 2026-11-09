#!/bin/bash
# Start SQL Helper from wherever this project lives (e.g. right after git clone).
#
#   ./run.sh                      run from Terminal
#   SQL_HELPER_PYTHON=/path/python3 ./run.sh    force a specific Python
#
# Finds a Python 3.10+ that has Tk 8.6+. Order: SQL_HELPER_PYTHON, python3 on
# PATH, python3 from your login shell (apps opened from Finder don't get your
# shell's PATH), then common install locations. macOS's /usr/bin/python3 is
# tried last because it often ships an old Tk 8.5.
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  local msg="$1"
  if [ -n "${SQL_HELPER_GUI:-}" ]; then
    # Launched from SQL Helper.app: there's no Terminal, so show a dialog.
    /usr/bin/osascript -e "display dialog \"${msg//\"/\\\"}\" with title \"SQL Helper\" buttons {\"OK\"} default button 1 with icon caution" >/dev/null 2>&1
  else
    echo "SQL Helper: $msg" >&2
  fi
  exit 1
}

is_suitable() {
  [ -n "$1" ] && [ -x "$1" ] && "$1" -c '
import sys, tkinter
sys.exit(0 if sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6 else 1)' >/dev/null 2>&1
}

find_python() {
  local candidates=()
  [ -n "${SQL_HELPER_PYTHON:-}" ] && candidates+=("$SQL_HELPER_PYTHON")
  candidates+=("$(command -v python3 2>/dev/null)")
  candidates+=("$(/bin/zsh -lic 'command -v python3' </dev/null 2>/dev/null | tail -n 1)")
  candidates+=(
    /opt/homebrew/bin/python3
    /usr/local/bin/python3
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3
    /opt/anaconda3/bin/python3 "$HOME/anaconda3/bin/python3"
    /opt/miniconda3/bin/python3 "$HOME/miniconda3/bin/python3"
    /usr/bin/python3
  )
  local py
  for py in "${candidates[@]}"; do
    if is_suitable "$py"; then echo "$py"; return 0; fi
  done
  return 1
}

PYTHON="$(find_python)" || fail "Couldn't find Python 3.10 or newer with Tk 8.6+. Install Python from python.org (it includes Tk), or with Homebrew run: brew install python python-tk"

cd "$PROJECT_DIR" || fail "Can't open the project folder: $PROJECT_DIR"

# macOS names a plain (non-bundled) process after its executable, so the Dock
# and menu bar would say "python3.x". Running Python through a link called
# "SQL Helper" makes them say "SQL Helper" instead. Python follows the link to
# find its own libraries, so nothing else changes. If the link can't be made,
# just use Python directly.
if [ "$(uname)" = "Darwin" ]; then
  mkdir -p .launcher 2>/dev/null && ln -sf "$PYTHON" ".launcher/SQL Helper" 2>/dev/null \
    && PYTHON="$PROJECT_DIR/.launcher/SQL Helper"
fi

if [ -n "${SQL_HELPER_GUI:-}" ]; then
  # No Terminal to print to, so keep output in a log for troubleshooting.
  mkdir -p user_data
  exec "$PYTHON" -m sql_helper >>user_data/launch.log 2>&1
fi
exec "$PYTHON" -m sql_helper
