# Generate Dockerfile.backend-base from Dockerfile.backend-deps.
#
# WHY: BuildKit layer cache keys are derived from the exact instruction bytes.
# Retyping the dependency layers (apt / adb / pip / playwright) risks a 1-byte difference
# that silently becomes a CACHE MISS on the expensive pip layer (observed 2026-10-10:
# pip had to re-resolve all 243 packages and then failed with connection errors).
# So the dependency instructions live in ONE place - Dockerfile.backend-deps - and this
# script only prepends documentation, never rewriting a single instruction byte.
#
# Single source of truth:
#   Dockerfile.backend-deps  -> raw dependency layers (edit these HERE)
#   scripts/gen_backend_base.py -> Dockerfile.backend-base = docs header + those bytes
#
# Usage: python scripts/gen_backend_base.py
# Then:  docker build -f Dockerfile.backend-base -t testhub-backend-base:<date> .

import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'Dockerfile.backend-deps')
DST = os.path.join(ROOT, 'Dockerfile.backend-base')

with io.open(SRC, 'r', encoding='utf-8', newline='') as f:
    body = f.read()

HEADER = u'''# syntax=docker/dockerfile:1
#
# TestHub backend BASE image - GENERATED FILE, do not edit by hand.
#   Source of truth for the dependency layers below: Dockerfile.backend-deps
#   (regenerate with: python scripts/gen_backend_base.py)
#
# Contains everything expensive and slow-changing:
#   - python base image (digest-pinned)
#   - apt system packages + adb
#   - Python dependencies from requirements.lock.txt (243 pkgs)
#   - Playwright Chromium + deps (~184MB browser)
# Dockerfile.backend then only does: FROM this image + COPY . . + CMD.
#
# WHY THIS FILE EXISTS
#   BuildKit layer caching is CHAIN-based: anything upstream changing invalidates all
#   later layers. Measured full rebuild cost: apt 5~20 min, pip 30~40 min,
#   playwright 30~50 min (~100 min total on 2026-10-10). Once the layers live in this
#   TAGGED image instead of only in the build cache, they survive BuildKit prunes.
#
# HOW TO REBUILD
#   1. python scripts/gen_backend_base.py          (regenerate; keeps bytes identical)
#   2. docker build -f Dockerfile.backend-base -t testhub-backend-base:<YYYYMMDD> .
#   3. docker tag testhub-backend-base:<YYYYMMDD> testhub-backend-base:latest
#   4. update the FROM line in Dockerfile.backend, then: docker compose build backend
#
# WHEN MUST THE BASE BE REBUILT?
#   - requirements.lock.txt changed                  (otherwise new packages are missing)
#   - system packages / playwright version changed    (rare)
#   - python base image upgraded (re-pin the digest to the new one)
#
# RULES
#   - NEVER use --no-cache.
#   - Safe cleanup: `docker image prune -f` (dangling images only). This image survives it
#     because it is tagged and Dockerfile.backend references its tag.
#   - NEVER run `docker system prune` / `docker builder prune` / Docker Desktop "Purge data":
#     those wipe BuildKit history and the pip cache mount.
#   - Verify the browser really landed after every base rebuild (the RUN is `|| echo` guarded,
#     so failures are SILENT):
#       docker run --rm testhub-backend-base:<tag> bash -lc \\
#         "ls -d /root/.cache/ms-playwright/chromium*/chrome-linux64 && \\
#          chromium-*/chrome-linux64/chrome --version"
#
'''

with io.open(DST, 'w', encoding='utf-8', newline='') as f:
    f.write(HEADER)
    f.write(body)

print('generated %s from %s (%d bytes)' % (DST, SRC, len(body)))
