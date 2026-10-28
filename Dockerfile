FROM python:3.13.18-slim-bookworm@sha256:89c04d97d1f3f0a04ea357a27d000ba4efb18536d2d68a54611f76d5c1b5fe99

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONNOUSERSITE=1 \
    AGENTSERVER_STATE_ROOT=/tmp/agentserver

WORKDIR /app
COPY agent/requirements.txt ./requirements.txt
COPY --from=runtime /packages ./packages
RUN PYTHONPATH=/app/packages python -m pip check
COPY agent/main.py ./main.py

USER 10001:10001
EXPOSE 8088
CMD ["python", "main.py"]
