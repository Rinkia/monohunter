# monohunter — reproducible run anywhere, no local Python setup.
#   docker build -t monohunter .
#   docker run --rm -v monohunter-data:/data monohunter run --tic 298663873 --sectors 19
#
# HOME and WORKDIR both point at /data, so the lightkurve/astroquery caches AND
# all outputs (candidates/, summaries/, sweeps/, state) live in one mounted volume.
# The container runs as a non-root user (uid 10001); use a NAMED volume as above
# (Docker chowns it to that user). A plain bind mount (-v "$PWD/data:/data") is
# root-owned on the host and won't be writable unless you `chown 10001 data` first.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HOME=/data \
    MPLBACKEND=Agg

WORKDIR /app
# Only what the build needs (pyproject reads README); keeps the context lean.
COPY pyproject.toml README.md ./
COPY monohunter ./monohunter
RUN pip install --no-cache-dir .

# Run as a non-root user: monohunter needs no privileges, and if a malicious FITS ever
# tripped a parser bug in a dependency, the blast radius is an unprivileged UID with only
# the mounted /data volume — not container-root. /data is created + owned so the volume is
# writable whether or not the host bind-mounts over it.
RUN useradd --uid 10001 --create-home --home-dir /data monohunter
USER monohunter

WORKDIR /data
ENTRYPOINT ["monohunter"]
CMD ["--help"]
