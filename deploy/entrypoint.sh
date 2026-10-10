#!/bin/sh
set -eu

# Both bundled immutable datasets are verified before the listener starts.
# The place catalog is opened with immutable=1 at runtime, which instructs
# SQLite to trust the file, so its integrity gate is not optional.  The image
# carries no catalogue producer; producer freshness is bound in the repository.
/opt/venv/bin/python /app/scripts/verification/verify_ephemeris_integrity.py --check
/opt/venv/bin/python /app/scripts/verification/verify_place_catalog.py --check --installed-image
exec "$@"
