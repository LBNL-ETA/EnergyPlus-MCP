# =============================================================================
# EnergyPlus MCP dev-container
# =============================================================================

# -----------------------------------------------------------------------------
# 0. Build-only stage: EnergyPlus reference documentation index
#
# Converts the Input Output Reference, Engineering Reference, Output Details and
# Examples, and Plant Application Guide from the LaTeX source of the same
# release tag as the engine (EPLUS_VER/EPLUS_HASH, shared with section 2) into
# a section index for the reference_docs tool.  git and pandoc stay in this
# stage; only the index (~20 MB) is copied into the final image.
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS reference-docs
ARG EPLUS_VER=26.1.0
ARG EPLUS_HASH=6f2e40d102
RUN apt-get update && \
    apt-get install -y --no-install-recommends git pandoc ca-certificates && \
    rm -rf /var/lib/apt/lists/*
COPY build_reference_docs.py /opt/build_reference_docs.py
RUN python /opt/build_reference_docs.py \
      --tag "v${EPLUS_VER}" --expected-commit "${EPLUS_HASH}" --out /reference-docs

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
# To build against a different EnergyPlus release, override these three build
# args together — e.g. to pin 25.1.0:
#   docker build \
#     --build-arg EPLUS_VER=25.1.0 \
#     --build-arg EPLUS_HASH=68a4a7c774 \
#     --build-arg EPLUS_PREFIX=/app/software/EnergyPlusV25-1-0 \
#     --build-arg EPLUS_DIST_SUFFIX=Ubuntu22.04 \
#     -t energyplus-mcp-dev -f .devcontainer/Dockerfile .devcontainer
# The EPLUS_HASH is the commit string NREL embeds in the release tarball name;
# get it from the filenames listed at https://github.com/NREL/EnergyPlus/releases
#
# The model-upgrade transition bundle below is intentionally pinned to this
# default 26.1.0 engine.  Alternate EPLUS_VER builds remain supported, but do
# not include the 9.2.0 -> 26.1.0 bundle unless this pairing is updated too.
# -----------------------------------------------------------------------------
# Keep the release build hash in sync with the official asset filename.
ARG EPLUS_VER=26.1.0
ARG EPLUS_HASH=6f2e40d102
ARG EPLUS_PREFIX=/app/software/EnergyPlusV26-1-0
# Use Ubuntu22.04 for <=25.1.0 and Ubuntu24.04 for >=26.1.0.
ARG EPLUS_DIST_SUFFIX=Ubuntu24.04

# Official v26.1.0 Linux archive SHA-256 values.  These checks apply only to
# the documented default engine so user-provided EPLUS_VER overrides continue
# to use their own release assets.
ARG EPLUS_26_1_ARM64_SHA256=1a27eb6a5be69ac1fbfb591b206c1cce5bf02a973c92d207b9fd7da459984208
ARG EPLUS_26_1_X86_64_SHA256=b651f4197bfc147a0f66dc92c58895d1748bdadb7a0288145fa9d50375edfbca

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
    EPLUS_SHA256=""; \
    if [ "$EPLUS_VER" = "26.1.0" ] && [ "$EPLUS_HASH" = "6f2e40d102" ] && [ "$EPLUS_DIST_SUFFIX" = "Ubuntu24.04" ]; then \
      if [ "$TARGETPLATFORM" = "linux/arm64" ]; then EPLUS_SHA256="$EPLUS_26_1_ARM64_SHA256"; fi; \
      if [ "$TARGETPLATFORM" = "linux/amd64" ]; then EPLUS_SHA256="$EPLUS_26_1_X86_64_SHA256"; fi; \
    fi; \
    mkdir -p ${EPLUS_PREFIX}; \
    wget -q "https://github.com/NREL/EnergyPlus/releases/download/v${EPLUS_VER}/EnergyPlus-${EPLUS_VER}-${EPLUS_HASH}-${EPLUS_DIST}.tar.gz" \
         -O /tmp/eplus.tgz; \
    if [ -n "$EPLUS_SHA256" ]; then echo "$EPLUS_SHA256  /tmp/eplus.tgz" | sha256sum -c -; fi; \
    tar -xzf /tmp/eplus.tgz -C ${EPLUS_PREFIX} --strip-components=1; \
    ln -s ${EPLUS_PREFIX}/energyplus /usr/local/bin/energyplus; \
    rm /tmp/eplus.tgz

# Reference documentation index built in stage 0 (read by reference_docs).
COPY --from=reference-docs /reference-docs ${EPLUS_PREFIX}/ReferenceDocs

# -----------------------------------------------------------------------------
# 3. Pinned native-Linux IDF transition assets for the default 26.1.0 engine.
#
# The v25.1.0 archives provide the 9.2.0 -> 25.1.0 hops.  v26.1.0 provides
# 25.1.0 -> 25.2.0 -> 26.1.0.  Checksums are from the official release
# manifests/API.  Nothing is fetched at runtime.
# -----------------------------------------------------------------------------
ARG EPLUS_TRANSITION_SOURCE_VER=25.1.0
ARG EPLUS_TRANSITION_SOURCE_HASH=68a4a7c774
ARG EPLUS_TRANSITION_SOURCE_DIST_SUFFIX=Ubuntu24.04
ARG EPLUS_25_1_ARM64_SHA256=50aa05b7dc1462771a04893206eba0b490391d854ecb5b30f09da979c3ef52e5
ARG EPLUS_25_1_X86_64_SHA256=faee846457ce450e8b2434e918cf70b551c4f59bea2b282711a498a6c878495a
COPY stage_energyplus_transitions.sh /usr/local/bin/stage-energyplus-transitions
RUN set -eux; \
    mkdir -p /app/software/energyplus-transitions; \
    if [ "$EPLUS_VER" != "26.1.0" ] || [ "$EPLUS_HASH" != "6f2e40d102" ] || [ "$EPLUS_DIST_SUFFIX" != "Ubuntu24.04" ]; then \
      echo "Staging only the installed updater for non-default EnergyPlus build"; \
      if [ -d "${EPLUS_PREFIX}/PreProcess/IDFVersionUpdater" ]; then \
        cp -a "${EPLUS_PREFIX}/PreProcess/IDFVersionUpdater/." /app/software/energyplus-transitions/; \
      fi; \
    else \
      if [ "$TARGETPLATFORM" = "linux/arm64" ]; then \
        TRANSITION_ARCH=arm64; TRANSITION_SHA256="$EPLUS_25_1_ARM64_SHA256"; \
      elif [ "$TARGETPLATFORM" = "linux/amd64" ]; then \
        TRANSITION_ARCH=x86_64; TRANSITION_SHA256="$EPLUS_25_1_X86_64_SHA256"; \
      else \
        echo "Unsupported platform: $TARGETPLATFORM" >&2; exit 1; \
      fi; \
      wget -q "https://github.com/NREL/EnergyPlus/releases/download/v${EPLUS_TRANSITION_SOURCE_VER}/EnergyPlus-${EPLUS_TRANSITION_SOURCE_VER}-${EPLUS_TRANSITION_SOURCE_HASH}-Linux-${EPLUS_TRANSITION_SOURCE_DIST_SUFFIX}-${TRANSITION_ARCH}.tar.gz" -O /tmp/eplus-transition-source.tgz; \
      echo "$TRANSITION_SHA256  /tmp/eplus-transition-source.tgz" | sha256sum -c -; \
      mkdir -p /tmp/eplus-transition-source; \
      tar -xzf /tmp/eplus-transition-source.tgz -C /tmp/eplus-transition-source --strip-components=1; \
      sh /usr/local/bin/stage-energyplus-transitions /app/software/energyplus-transitions /tmp/eplus-transition-source/PreProcess/IDFVersionUpdater ${EPLUS_PREFIX}/PreProcess/IDFVersionUpdater; \
      rm -rf /tmp/eplus-transition-source /tmp/eplus-transition-source.tgz; \
    fi

# ----------------------------------------------------------------------------- 
# 4. Runtime environment variables
# ----------------------------------------------------------------------------- 
ENV PATH="${EPLUS_PREFIX}:${PATH}" \
    EPLUS_IDD_PATH="${EPLUS_PREFIX}/Energy+.idd" \
    EPLUS_TRANSITION_DIR="/app/software/energyplus-transitions"

# ----------------------------------------------------------------------------- 
# 5. Language-specific tooling
# ----------------------------------------------------------------------------- 
# Python package manager (uv)
RUN pip install --no-cache-dir uv

# ----------------------------------------------------------------------------- 
# 6. Non-root user (for VS Code Remote-Containers)
# ----------------------------------------------------------------------------- 
RUN useradd --create-home --shell /bin/bash vscode
USER vscode

# ----------------------------------------------------------------------------- 
# 7. Workspace location and default shell
# ----------------------------------------------------------------------------- 
WORKDIR /workspace/energyplus-mcp-server
CMD ["/bin/bash"]
