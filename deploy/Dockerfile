# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM python:3.14.10-slim-trixie@sha256:b6c548779edc1457339ef930a3914a788a74ee592993dbc19dfcecc08d2c5e26 AS builder

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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

# Install the toolchain from the same Debian snapshot the pinned base
# image records in its sources (20261020T213255Z, the commented snapshot URIs
# of its /etc/apt/sources.list.d/debian.sources), not from whatever the mirror
# serves on build day.  The snapshot's Release files are past their
# Valid-Until, so that check is off; they are fetched over HTTPS so a party on
# the path cannot replay an older, still validly signed Release.  pkg-config
# and libsqlite3-dev make pyswisseph's setup.py link Debian's libsqlite3 (security-maintained, the runtime base
# already carries libsqlite3-0) instead of compiling Swephelp's bundled SQLite.
ARG DEBIAN_SNAPSHOT=20261020T213255Z
RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|https://snapshot.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
        -e "s|http://deb.debian.org/debian|https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}|" \
        /etc/apt/sources.list.d/debian.sources \
    && grep -q "https://snapshot.debian.org/archive/debian/${DEBIAN_SNAPSHOT}" /etc/apt/sources.list.d/debian.sources \
    && ! grep -q 'deb.debian.org' /etc/apt/sources.list.d/debian.sources \
    && ! grep -q '^URIs: http:' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Check-Valid-Until=false update \
    && apt-get install --yes --no-install-recommends build-essential pkg-config libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/requirements.lock /build/requirements.lock
COPY deploy/build-requirements.lock /build/build-requirements.lock
COPY third_party/pyswisseph/pyswisseph-2.10.3.2.tar.gz /source/pyswisseph-2.10.3.2.tar.gz
# The locked wheels, downloaded and hash-checked by build_release_image before
# the build; pip below reads only this directory, in a step with no network.
COPY wheelhouse /wheelhouse

# The image build needs only pyswisseph's build backend (setuptools and
# wheel), so only those two pinned entries of build-requirements.lock are
# installed, and every other distribution must arrive as a wheel.
RUN --network=none python -c 'import re,sys; from pathlib import Path; blocks=re.findall(r"^((?:setuptools|wheel)==[^\n]*(?:\n[ \t]+[^\n]*)*)", Path("/build/build-requirements.lock").read_text(), flags=re.M); names=sorted(b.split("==")[0] for b in blocks); names==["setuptools","wheel"] or sys.exit("image build lock subset is not exactly setuptools and wheel"); Path("/build/image-build.lock").write_text("\n".join(re.sub(r"\n[ \t]+#.*", "", b) for b in blocks)+"\n")' \
    && python -m venv /opt/venv \
    && mkdir --parents /wheels \
    && python -m pip install \
        --disable-pip-version-check \
        --no-index \
        --find-links /wheelhouse \
        --require-hashes \
        --no-deps \
        --requirement /build/image-build.lock \
    && python -m pip wheel \
        --disable-pip-version-check \
        --no-index \
        --find-links /wheelhouse \
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
        'import platform,sys,swisseph; ok=platform.python_version()=="3.14.10" and swisseph.version=="2.10.03"; sys.exit(0 if ok else "Python or Swiss Ephemeris version mismatch")' \
    && ldd /opt/venv/lib/python3.14/site-packages/swisseph.*.so | grep -q 'libsqlite3\.so\.0 => /' \
    && /opt/venv/bin/python -m pip uninstall --yes pip \
    && find /opt/venv -depth -type d -name __pycache__ -exec rm --recursive {} +

# The licence texts of what the extension compiles, taken from the exact sdist
# above: the runtime image's THIRD_PARTY_NOTICES.md names them.
RUN --network=none mkdir --parents /licenses \
    && tar --extract --gzip --to-stdout --file /source/pyswisseph-2.10.3.2.tar.gz \
        pyswisseph-2.10.3.2/LICENSE.txt > /licenses/LICENSE.txt \
    && tar --extract --gzip --to-stdout --file /source/pyswisseph-2.10.3.2.tar.gz \
        pyswisseph-2.10.3.2/libswe/LICENSE > /licenses/SWISS_EPHEMERIS_LICENSE \
    && tar --extract --gzip --to-stdout --file /source/pyswisseph-2.10.3.2.tar.gz \
        pyswisseph-2.10.3.2/swephelp/LICENSE.txt > /licenses/SWEPHELP_LICENSE \
    && grep -q 'GNU AFFERO GENERAL PUBLIC LICENSE' /licenses/LICENSE.txt \
    && grep -q 'This file is part of Swiss Ephemeris' /licenses/SWISS_EPHEMERIS_LICENSE \
    && grep -q 'GNU GENERAL PUBLIC LICENSE' /licenses/SWEPHELP_LICENSE

FROM python:3.14.10-slim-trixie@sha256:b6c548779edc1457339ef930a3914a788a74ee592993dbc19dfcecc08d2c5e26

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

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
      org.opencontainers.image.source="https://github.com/sa3952/Armillary" \
      org.projectarmillary.publication.status="${PUBLICATION_STATUS}" \
      org.classical-astrology.frontend.mode="external-release-v1"

ENV CLASSICAL_ASTROLOGY_REQUIRE_FRONTEND_RELEASE="1" \
    CLASSICAL_ASTROLOGY_SOURCE_REVISION="${VCS_REF}" \
    LANG="C.UTF-8" \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONFAULTHANDLER="1" \
    PYTHONUNBUFFERED="1" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONPYCACHEPREFIX="/opt/pycache"

WORKDIR /app

# Each dpkg-query result is captured on its own, so that `set -e` stops the
# build when the package database cannot be read instead of an empty list
# meaning "nothing to purge, nothing survived".
RUN set -eux; \
    packages="$(dpkg-query -W -f='${binary:Package}\t${Essential}\n')"; \
    removable="$(printf '%s\n' "$packages" \
        | awk '$2 != "yes" && ($1 == "perl" || $1 ~ /^perl-/ || $1 ~ /^libperl/ || $1 ~ /-perl(:[^:]+)?$/) { print $1 }')"; \
    if [ -n "$removable" ]; then \
        apt-get purge --yes $removable; \
    fi; \
    perl_base="$(dpkg-query -W -f='${db:Status-Abbrev} ${Essential}\n' perl-base)"; \
    [ "$perl_base" = "ii  yes" ]; \
    packages="$(dpkg-query -W -f='${binary:Package}\t${Essential}\n')"; \
    if printf '%s\n' "$packages" \
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

# Largest and least often changed first, so a code change rebuilds only the
# small layers after it.
COPY backend/place_data /app/backend/place_data
COPY backend/ephe /app/backend/ephe
COPY backend/app /app/backend/app
COPY deploy/ephemeris.sha256 /app/deploy/ephemeris.sha256
COPY deploy/frontend-contract.json /app/deploy/frontend-contract.json
COPY deploy/entrypoint.sh /app/deploy/entrypoint.sh
COPY deploy/container_healthcheck.py /app/deploy/container_healthcheck.py
COPY scripts/verification/verify_ephemeris_integrity.py /app/scripts/verification/verify_ephemeris_integrity.py
COPY scripts/verification/verify_place_catalog.py /app/scripts/verification/verify_place_catalog.py
COPY LICENSE /app/LICENSE
COPY --from=builder /licenses/LICENSE.txt /app/third_party/pyswisseph/LICENSE.txt
COPY --from=builder /licenses/SWISS_EPHEMERIS_LICENSE /app/third_party/pyswisseph/SWISS_EPHEMERIS_LICENSE
COPY --from=builder /licenses/SWEPHELP_LICENSE /app/third_party/pyswisseph/SWEPHELP_LICENSE

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

# Bytecode, compiled once here: the root filesystem is read-only at run time,
# so without it every worker of every start (and every health probe) compiles
# each module it imports again.  The venv and the application are compiled
# whole; of the standard library only the modules a started worker, the
# entrypoint checks and the health probe import (the rest would add ~11 MB for
# modules that are never loaded).  The cache sits under PYTHONPYCACHEPREFIX,
# outside /app, so the /app tree stays exactly the copied sources.
# unchecked-hash .pyc files carry no timestamps (reproducible) and are never
# revalidated, which is right for files that cannot change.
RUN python -c 'import py_compile, sys; sys.path.insert(0, "/app/backend"); import app.main, uvicorn.main, uvicorn.server, uvicorn.config, uvicorn.supervisors.multiprocess, uvicorn.protocols.http.h11_impl, uvicorn.lifespan.on, uvicorn.loops.asyncio, uvicorn.middleware.proxy_headers, argparse, hashlib, sqlite3, urllib.request, urllib.error; files = sorted({m.__file__ for m in list(sys.modules.values()) if (getattr(m, "__file__", None) or "").startswith("/usr/local/lib/python3.14/") and m.__file__.endswith(".py")}); len(files) > 100 or sys.exit("too few standard-library modules found to precompile"); [py_compile.compile(f, doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH) for f in files]' \
    && python -m compileall -q -j 0 --invalidation-mode unchecked-hash \
        /opt/venv/lib/python3.14/site-packages \
        /app/backend/app /app/scripts/verification /app/deploy/container_healthcheck.py

RUN chmod 0555 /app/deploy/entrypoint.sh \
    /app/deploy/container_healthcheck.py \
    /app/scripts/verification/verify_ephemeris_integrity.py \
    /app/scripts/verification/verify_place_catalog.py \
    && find /app /opt/venv /opt/pycache -type d -exec chmod 0555 {} + \
    && find /app /opt/venv /opt/pycache -type f -exec chmod go-w {} +

# A service that never installs a package, logs anyone in, changes user or
# account, or mounts anything needs none of the tools for it, so code running
# as the application user finds none of them.  This runs last because the
# steps above still query the package database; the database itself stays, so
# image scanners still see every package the base installed.  Gate D compares
# what is left with deploy/image-executables.json.
RUN set -eu; \
    for tool in \
        apt apt-cache apt-cdrom apt-config apt-get apt-mark \
        dpkg dpkg-deb dpkg-divert dpkg-maintscript-helper dpkg-query dpkg-realpath dpkg-split \
        dpkg-statoverride dpkg-trigger dpkg-preconfigure dpkg-reconfigure \
        debconf debconf-apt-progress debconf-communicate debconf-copydb debconf-escape \
        debconf-set-selections debconf-show update-alternatives deb-systemd-helper deb-systemd-invoke \
        su sg newgrp login sulogin runuser passwd chage chfn chsh expiry gpasswd \
        chpasswd chgpasswd newusers useradd userdel usermod groupadd groupdel groupmod \
        adduser addgroup deluser delgroup vipw vigr pwck grpck pwconv pwunconv grpconv grpunconv \
        shadowconfig faillock unix_chkpwd unix_update pam-auth-update pam_getenv pam_timestamp_check \
        pam_namespace_helper pwhistory_helper mkhomedir_helper \
        mount umount losetup swapon swapoff mkswap swaplabel mkfs fsck findfs blkid blkdiscard blkzone \
        blockdev wipefs fsfreeze fstrim isosize zramctl chcpu chmem ldattach rtcwake readprofile \
        nsenter unshare setpriv chroot pivot_root switch_root mknod \
        agetty getty start-stop-daemon invoke-rc.d update-rc.d service policy-rc.d installkernel \
        add-shell remove-shell update-shells update-passwd \
        perl; do \
        rm -f "/usr/bin/$tool" "/usr/sbin/$tool"; \
    done; \
    rm -f /usr/bin/perl5.*; \
    for tool in apt-get dpkg su mount nsenter unshare setpriv perl; do \
        if [ -e "/usr/bin/$tool" ] || [ -e "/usr/sbin/$tool" ]; then \
            echo "$tool survived the tool removal" >&2; exit 1; \
        fi; \
    done

USER 10001:10001
EXPOSE 8000

# Every 30 s: liveness, plus a synthetic chart and place search every 10th run
# and after any failure; three consecutive failures in a container that was
# healthy once make the probe end PID 1 so the restart policy restarts it
# (deploy/container_healthcheck.py).  A busy 503 is never a failure; after ten
# minutes of nothing else the container is marked unhealthy, not restarted.
# The 45 s timeout covers liveness and readiness (3.5 s each), a chart that
# waits out the 18 s queue budget (25 s) and the place search (8 s).  Start
# runs are 2 s apart (Docker >= 25).
HEALTHCHECK --interval=30s --timeout=45s --start-period=60s --start-interval=2s --retries=3 \
    CMD ["/opt/venv/bin/python", "/app/deploy/container_healthcheck.py"]

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
# Worker health-check timeout 5 s: while uvicorn's supervisor
# waits on a recycled worker the other one carries the site, so a shorter wait
# shortens the window in which both are out (a fresh worker is ready in ~2.5 s).
# No header-read timeout exists in uvicorn/h11; slow headers are bounded by the
# edge (client_header_timeout 5s), and the app port is never published.
CMD ["/opt/venv/bin/python", "-m", "uvicorn", "app.main:create_app", "--factory", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--loop", "asyncio", "--http", "h11", "--ws", "none", "--no-access-log", "--no-server-header", "--timeout-worker-healthcheck", "5", "--timeout-graceful-shutdown", "25", "--backlog", "32", "--limit-max-requests", "1000", "--limit-max-requests-jitter", "200", "--no-proxy-headers"]
