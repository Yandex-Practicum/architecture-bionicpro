FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
      PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir -r requirements.txt; fi
COPY --chown=1000:1000 main.py profiles.py .
RUN mkdir /data && chown 1000:1000 /data
USER 1000:1000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
