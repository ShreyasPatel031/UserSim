FROM runloop/universal-ubuntu-24.04-x86_64

ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright \
    PYTHONUNBUFFERED=1

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb fonts-liberation libnss3 libgbm1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/usersim
COPY mvp/requirements.txt /opt/usersim/mvp/requirements.txt

RUN uv venv /opt/usersim/.venv \
    && /opt/usersim/.venv/bin/pip install --no-cache-dir \
      browser-use==0.13.8 browserbase playwright mangum \
      fastapi httpx pydantic typing-extensions==4.15.0 \
      google-auth google-cloud-aiplatform pyotp \
    && /opt/usersim/.venv/bin/playwright install --with-deps chromium \
    && ln -s "$(find /opt/ms-playwright -type f -path '*/chrome-linux*/chrome' | head -1)" /usr/local/bin/chromium

ENV PATH="/opt/usersim/.venv/bin:${PATH}"

# Source code and all credentials are mounted or cloned at runtime. In
# particular, Google credentials and authenticated browser profiles must never
# be copied into this image.
CMD ["sleep", "infinity"]
