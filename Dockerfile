# syntax=docker/dockerfile:1
FROM python:3.13-alpine AS checked-source
WORKDIR /source
COPY pyproject.toml ./
COPY host_metrics/ host_metrics/
COPY tools/install_release.py tools/install_release.py
COPY tests/ tests/
RUN PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v

FROM python:3.13-alpine AS runtime
ARG SERVICE_REVISION=development
ENV SERVICE_REVISION=$SERVICE_REVISION
LABEL org.opencontainers.image.revision=$SERVICE_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY --from=checked-source /source/pyproject.toml ./
COPY --from=checked-source /source/host_metrics/ host_metrics/
USER 65534:65534
ENTRYPOINT ["python", "-m", "host_metrics"]
CMD ["collect", "--data-dir", "/data", "--disk", "/data", "--proc-root", "/host/proc"]
