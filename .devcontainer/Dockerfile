FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Wine lets this Linux Codespace run Windows Python and PyInstaller for local
# Windows x64 builds. The extracted x64 Python runtime needs only Wine64.
# The upstream image includes Yarn's apt source with an expired/missing key.
# NUP does not use Yarn; disable its source rather than weaken apt verification.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        unzip \
        file \
        wine \
        wine64 \
        xvfb \
        xauth \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Extract official Windows Python components without running the MSI engine.
RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends msitools \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# pip --user installs the NUP CLI here for the configured remote user.
ENV PATH="/home/vscode/.local/bin:${PATH}"
