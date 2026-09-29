FROM python:3.13-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc binutils libc6-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements*.txt ./
RUN pip install --no-cache-dir -r requirements-build.txt
COPY main.py pages.py relay_vless.py speed_limit.py telegram_bot.py xhttp_siz10.py ./
COPY tools/ ./tools/
RUN python tools/build_obfuscated.py --output /release

FROM python:3.13-slim
WORKDIR /app
COPY --from=builder /release/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=builder /release/ ./
ENV DATA_DIR=/data
EXPOSE 8000
CMD ["python", "run.py"]
