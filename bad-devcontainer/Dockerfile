FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Wine lets this Linux Codespace run Windows Python and PyInstaller for local
# Windows builds. i386 is required by Debian's wine32 package.
# The upstream image includes Yarn's apt source with an expired/missing key.
# NUP does not use Yarn; disable its source rather than weaken apt verification.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && dpkg --add-architecture i386 \
    && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 update \
    && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        unzip \
        file \
        wine \
        wine64 \
        wine32 \
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
