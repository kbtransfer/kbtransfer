FROM python:3.12-slim

RUN useradd --create-home --uid 10001 kbt
WORKDIR /srv/kbtransfer

COPY . /srv/kbtransfer
RUN pip install --no-cache-dir -e ".[server]"

USER kbt
ENV KBTRANSFER_REGISTRY_ROOT=/srv/registry \
    KBTRANSFER_TRUST_ROLE=open \
    KBTRANSFER_COMMIT_MODE=auto \
    KBTRANSFER_MAX_BYTES=268435456 \
    PORT=8080

EXPOSE 8080
CMD ["sh", "-c", "uvicorn examples.sample-registry-http.app:app --host 0.0.0.0 --port ${PORT}"]
