#!/bin/sh
# Snapshot /app code into a tarball so two images can be diffed on the host.
# Must stay LF (see .gitattributes) - it runs with `sh` inside the container.
cd /app || exit 1
rm -f /tmp/app_snap.tar
tar -cf /tmp/app_snap.tar apps backend *.py *.md 2>/dev/null
echo "--- snapshot ---"
ls -la /tmp/app_snap.tar
md5sum /tmp/app_snap.tar
