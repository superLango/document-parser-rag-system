FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /engine

COPY services/sandbox/runtime/runner.py /engine/runner.py
COPY services/sandbox/runtime/builtin.py /engine/builtin.py
COPY services/sandbox/runtime/prepare.py /engine/prepare.py

# The workspace is mounted at /work. These symlinks keep the documented
# /input, /recipes, /templates and /output layout for recipe code.
RUN mkdir -p /work \
    && ln -s /work/input /input \
    && ln -s /work/recipes /recipes \
    && ln -s /work/templates /templates \
    && ln -s /work/output /output \
    && chmod 0555 /engine \
    && chmod 0444 /engine/*.py

USER 65534:65534

ENTRYPOINT ["python", "-B", "/engine/runner.py"]
