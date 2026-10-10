# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM python:3.14.8-slim-trixie@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151 AS builder

# Keep compiler-produced archives independent of wall-clock time.
ENV SOURCE_DATE_EPOCH="0" \
    PIP_DISABLE_PIP_VERSION_CHECK="1" \
    PIP_NO_CACHE_DIR="1" \
    PYTHONDONTWRITEBYTECODE="1"

# pyswisseph includes C++ translation units. Pin both compilation and shared
# linking; the runtime stage imports the extension to prove libstdc++ is there.
ENV CXX="g++" \
    LDSHARED="g++ -shared" \
    LDCXXSHARED="g++ -shared"

WORKDIR /build

# OPS-26: install the toolchain from the same Debian snapshot the pinned base
# image records in its sources (20260918T000000Z), not from whatever the mirror
# serves on build day.  OPS-28: pkg-config and libsqlite3-dev make pyswisseph's
# setup.py link Debian's libsqlite3 (security-maintained, the runtime base
# already carries libsqlite3-0) instead of compiling Swephelp's bundled SQLite.
ARG DEBIAN_SNAPSHOT=20260918T000000Z
RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|http://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
        -e "s|http://deb.debian.org/debian|http://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
        /etc/apt/sources.list.d/debian.sources \
    && grep -q "snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" /etc/apt/sources.list.d/debian.sources \
    && ! grep -q 'deb.debian.org' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install --yes --no-install-recommends build-essential pkg-config libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/requirements.lock /build/requirements.lock
COPY deploy/build-requirements.lock /build/build-requirements.lock
COPY third_party/pyswisseph/pyswisseph-2.10.3.2.tar.gz /source/pyswisseph-2.10.3.2.tar.gz

# OPS-27: the image build needs only pyswisseph's build backend (setuptools and
# wheel), so only those two pinned entries of build-requirements.lock are
# installed, and every other distribution must arrive as a wheel.
RUN python -c 'import re,sys; from pathlib import Path; blocks=re.findall(r"^((?:setuptools|wheel)==[^\n]*(?:\n[ \t]+[^\n]*)*)", Path("/build/build-requirements.lock").read_text(), flags=re.M); names=sorted(b.split("==")[0] for b in blocks); names==["setuptools","wheel"] or sys.exit("image build lock subset is not exactly setuptools and wheel"); Path("/build/image-build.lock").write_text("\n".join(re.sub(r"\n[ \t]+#.*", "", b) for b in blocks)+"\n")' \
    && python -m venv /opt/venv \
    && mkdir --parents /wheels \
    && python -m pip install \
        --disable-pip-version-check \
        --require-hashes \
        --no-deps \
        --requirement /build/image-build.lock \
    && python -m pip wheel \
        --disable-pip-version-check \
        --require-hashes \
        --no-build-isolation \
        --only-binary=:all: \
        --no-binary=pyswisseph \
        --wheel-dir /wheels \
        'file:///source/pyswisseph-2.10.3.2.tar.gz#sha256=c54c305e83dbd5d2b71e58d8a69d8ee41de24c4d3328ce09e2af860a3537624d' \
        --requirement /build/requirements.lock \
    && find /wheels -type f -name '*.whl' -exec \
        /opt/venv/bin/python -m pip install \
        --disable-pip-version-check \
        --no-index \
        --no-deps \
        {} + \
    && /opt/venv/bin/python -c \
        'import platform,sys,swisseph; ok=platform.python_version()=="3.14.8" and swisseph.version=="2.10.03"; sys.exit(0 if ok else "Python or Swiss Ephemeris version mismatch")' \
    && ldd /opt/venv/lib/python3.14/site-packages/swisseph.*.so | grep -q 'libsqlite3\.so\.0 => /' \
    && /opt/venv/bin/python -m pip uninstall --yes pip

FROM python:3.14.8-slim-trixie@sha256:c3e521df8b2b498a7a682e7e18676771cb80c6b75b8699af886b2d554ce40151

ARG VCS_REF
ARG PUBLICATION_STATUS
RUN case "${VCS_REF}" in \
      ????????????????????????????????????????) \
        case "${VCS_REF}" in *[!0-9a-f]*) false ;; *) true ;; esac ;; \
      *) false ;; \
    esac \
    && case "${PUBLICATION_STATUS}" in \
      provisional_unpublished|published_anonymously_reachable) true ;; \
      *) false ;; \
    esac
LABEL org.opencontainers.image.title="Classical Astrology" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="public Git exact revision and release source archive" \
      org.projectarmillary.publication.status="${PUBLICATION_STATUS}" \
      org.classical-astrology.frontend.mode="external-release-v1"

ENV CLASSICAL_ASTROLOGY_REQUIRE_FRONTEND_RELEASE="1" \
    CLASSICAL_ASTROLOGY_SOURCE_REVISION="${VCS_REF}" \
    LANG="C.UTF-8" \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONFAULTHANDLER="1" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1"

WORKDIR /app

RUN set -eux; \
    removable="$(dpkg-query -W -f='${binary:Package}\t${Essential}\n' \
        | awk '$2 != "yes" && ($1 == "perl" || $1 ~ /^perl-/ || $1 ~ /^libperl/ || $1 ~ /-perl(:[^:]+)?$/) { print $1 }')"; \
    if [ -n "$removable" ]; then \
        apt-get purge --yes $removable; \
    fi; \
    dpkg-query -W -f='${db:Status-Abbrev} ${Essential}\n' perl-base \
        | grep -q '^ii  yes$'; \
    if dpkg-query -W -f='${binary:Package}\t${Essential}\n' \
        | awk '$2 != "yes" && ($1 == "perl" || $1 ~ /^perl-/ || $1 ~ /^libperl/ || $1 ~ /-perl(:[^:]+)?$/) { found=1 } END { exit !found }'; then \
        echo "non-essential Perl survived the purge" >&2; exit 1; \
    fi; \
    python -m pip uninstall --yes pip \
    && rm --recursive /usr/local/lib/python3.14/ensurepip \
    && groupadd --gid 10001 astrology \
    && useradd \
        --uid 10001 \
        --gid 10001 \
        --no-create-home \
        --home-dir /nonexistent \
        --shell /usr/sbin/nologin \
        astrology \
    && rm --recursive --force /var/lib/apt/lists/* \
    && find / -xdev -type f -perm /6000 -exec chmod a-s {} +

COPY --from=builder /opt/venv /opt/venv

# The extension records libstdc++.so.6 and libsqlite3.so.0 as needed, so the
# runtime layer must carry both.  Read back from the installed package database
# rather than assumed from the base image's reputation, and placed before the
# application so a missing runtime fails the build instead of the first request.
RUN dpkg-query -W -f='${db:Status-Abbrev}\n' libstdc++6 | grep -q '^ii ' \
    && dpkg-query -W -f='${db:Status-Abbrev}\n' libsqlite3-0 | grep -q '^ii ' \
    && /opt/venv/bin/python -c 'import swisseph; print(swisseph.version)'

COPY backend/app /app/backend/app
COPY backend/ephe /app/backend/ephe
COPY backend/place_data /app/backend/place_data
COPY deploy/ephemeris.sha256 /app/deploy/ephemeris.sha256
COPY deploy/frontend-contract.json /app/deploy/frontend-contract.json
COPY deploy/entrypoint.sh /app/deploy/entrypoint.sh
COPY deploy/container_healthcheck.py /app/deploy/container_healthcheck.py
COPY scripts/verification/verify_ephemeris_integrity.py /app/scripts/verification/verify_ephemeris_integrity.py
COPY scripts/verification/verify_place_catalog.py /app/scripts/verification/verify_place_catalog.py
COPY LICENSE /app/LICENSE

RUN --mount=type=bind,target=/build-context,readonly \
    if [ -f /build-context/THIRD_PARTY_NOTICES.md ]; then \
        install -m 0444 /build-context/THIRD_PARTY_NOTICES.md \
            /app/THIRD_PARTY_NOTICES.md; \
    elif [ -f /build-context/publication/public_overlay/THIRD_PARTY_NOTICES.md ]; then \
        install -m 0444 \
            /build-context/publication/public_overlay/THIRD_PARTY_NOTICES.md \
            /app/THIRD_PARTY_NOTICES.md; \
    else \
        echo "missing THIRD_PARTY_NOTICES.md in supported build context" >&2; \
        exit 1; \
    fi

RUN chmod 0555 /app/deploy/entrypoint.sh \
    /app/deploy/container_healthcheck.py \
    /app/scripts/verification/verify_ephemeris_integrity.py \
    /app/scripts/verification/verify_place_catalog.py \
    && find /app /opt/venv -type d -exec chmod 0555 {} + \
    && find /app /opt/venv -type f -exec chmod go-w {} +

USER 10001:10001
EXPOSE 8000

# Every 30 s: liveness, plus a synthetic chart and place search every 10th run
# and after any failure; three consecutive failures in a container that was
# healthy once make the probe end PID 1 so the restart policy restarts it
# (deploy/container_healthcheck.py).  A busy 503 is not a failure until it has
# lasted ten minutes.  The 40 s timeout covers liveness (2 s), a chart that
# waits out the 18 s queue budget (25 s) and the place search (8 s).  Start
# runs are 2 s apart (Docker >= 25).
HEALTHCHECK --interval=30s --timeout=40s --start-period=60s --start-interval=2s --retries=3 \
    CMD ["/opt/venv/bin/python", "/app/deploy/container_healthcheck.py"]

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["/opt/venv/bin/python", "-m", "uvicorn", "app.main:create_app", "--factory", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--loop", "asyncio", "--http", "h11", "--ws", "none", "--no-access-log", "--timeout-worker-healthcheck", "5", "--timeout-graceful-shutdown", "25", "--backlog", "32"]
