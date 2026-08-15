# monohunter — reproducible run anywhere, no local Python setup.
#   docker build -t monohunter .
#   docker run --rm -v "$PWD/data:/data" monohunter run --tic 298663873 --sectors 19
#
# HOME and WORKDIR both point at /data, so the lightkurve/astroquery caches AND
# all outputs (candidates/, summaries/, sweeps/, state) live in one mounted volume.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    HOME=/data \
    MPLBACKEND=Agg

WORKDIR /app
# Only what the build needs (pyproject reads README); keeps the context lean.
COPY pyproject.toml README.md ./
COPY monohunter ./monohunter
RUN pip install --no-cache-dir .

WORKDIR /data
ENTRYPOINT ["monohunter"]
CMD ["--help"]
