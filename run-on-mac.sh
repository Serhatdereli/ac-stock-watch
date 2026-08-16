#!/bin/bash
# ---------------------------------------------------------------------------
# Mac runner for the portable AC stock watcher (browser add-on).
#
# The cloud job (GitHub Actions) covers B&Q, Screwfix and Toolstation every
# 30 minutes, and needs nothing from this machine.
#
# This script covers John Lewis, which only reveals its stock to a real
# browser. It drives Chrome with the window parked off-screen, so nothing
# appears over your work. It runs only while the Mac is awake.
#
# Argos and Currys are NOT covered - see the notes at the top of
# browser_check.py for exactly what was tried and why they refuse.
#
# Your ntfy topic lives in .ntfy-topic next to this script and is
# deliberately never committed, so it stays private despite the public repo.
# ---------------------------------------------------------------------------

cd "$(dirname "$0")" || exit 1

if [ ! -f .ntfy-topic ]; then
  echo "Missing .ntfy-topic file - cannot send notifications." >&2
  exit 1
fi
export NTFY_TOPIC="$(tr -d '[:space:]' < .ntfy-topic)"

./.venv/bin/python browser_check.py >> ac-stock-watch.log 2>&1

# Keep the log from growing forever (last 2000 lines is plenty).
tail -n 2000 ac-stock-watch.log > ac-stock-watch.log.tmp && mv ac-stock-watch.log.tmp ac-stock-watch.log
