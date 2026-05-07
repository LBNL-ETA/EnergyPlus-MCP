# =============================================================================
# EnergyPlus MCP dev-container
# =============================================================================
FROM python:3.12-slim

# ----------------------------------------------------------------------------- 
# Allow Docker to pass along the target platform (e.g., linux/amd64 or linux/arm64)
# ----------------------------------------------------------------------------- 
ARG TARGETPLATFORM

# ----------------------------------------------------------------------------- 
# 1. System packages + Node.js 20 + minimal X11 libraries for EnergyPlus
# ----------------------------------------------------------------------------- 
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl wget git vim nano build-essential gnupg \
        libx11-6 libxext6 libxrender1 libxtst6 libxi6 libxrandr2 libxinerama1 libxcursor1 \
        graphviz \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# -----------------------------------------------------------------------------
# 2. EnergyPlus (auto-detect host architecture)
#
# To build against a different EnergyPlus release, override these four build
# args together — e.g. to pin 25.1.0:
#   docker build \
#     --build-arg EPLUS_VER=25.1.0 \
#     --build-arg EPLUS_HASH=68a4a7c774 \
#     --build-arg EPLUS_PREFIX=/app/software/EnergyPlusV25-1-0 \
#     --build-arg EPLUS_DIST_SUFFIX=Ubuntu22.04 \
#     -t energyplus-mcp-dev -f .devcontainer/Dockerfile .devcontainer
# The EPLUS_HASH is the commit string NREL embeds in the release tarball name;
# get it from the filenames listed at https://github.com/NREL/EnergyPlus/releases
# -----------------------------------------------------------------------------
ARG EPLUS_VER=26.1.0
ARG EPLUS_HASH=6f2e40d102                    # update when bumping version
ARG EPLUS_PREFIX=/app/software/EnergyPlusV26-1-0
ARG EPLUS_DIST_SUFFIX=Ubuntu24.04            # Ubuntu22.04 for <=25.1.0, Ubuntu24.04 for >=26.1.0

# Compute EPLUS_DIST based on TARGETPLATFORM and then download/unpack
RUN set -eux; \
    if [ "$TARGETPLATFORM" = "linux/arm64" ]; then \
      EPLUS_DIST="Linux-${EPLUS_DIST_SUFFIX}-arm64"; \
    elif [ "$TARGETPLATFORM" = "linux/amd64" ]; then \
      EPLUS_DIST="Linux-${EPLUS_DIST_SUFFIX}-x86_64"; \
    else \
      echo "Unsupported platform: $TARGETPLATFORM" >&2; \
      exit 1; \
    fi; \
    mkdir -p ${EPLUS_PREFIX}; \
    wget -q "https://github.com/NREL/EnergyPlus/releases/download/v${EPLUS_VER}/EnergyPlus-${EPLUS_VER}-${EPLUS_HASH}-${EPLUS_DIST}.tar.gz" \
         -O /tmp/eplus.tgz; \
    tar -xzf /tmp/eplus.tgz -C ${EPLUS_PREFIX} --strip-components=1; \
    ln -s ${EPLUS_PREFIX}/energyplus /usr/local/bin/energyplus; \
    rm /tmp/eplus.tgz

# ----------------------------------------------------------------------------- 
# 3. Runtime environment variables
# ----------------------------------------------------------------------------- 
ENV PATH="${EPLUS_PREFIX}:${PATH}" \
    EPLUS_IDD_PATH="${EPLUS_PREFIX}/Energy+.idd"

# ----------------------------------------------------------------------------- 
# 4. Language-specific tooling
# ----------------------------------------------------------------------------- 
# Python package manager (uv)
RUN pip install --no-cache-dir uv

# ----------------------------------------------------------------------------- 
# 5. Non-root user (for VS Code Remote-Containers)
# ----------------------------------------------------------------------------- 
RUN useradd --create-home --shell /bin/bash vscode
USER vscode

# ----------------------------------------------------------------------------- 
# 6. Workspace location and default shell
# ----------------------------------------------------------------------------- 
WORKDIR /workspace/energyplus-mcp-server
CMD ["/bin/bash"]
