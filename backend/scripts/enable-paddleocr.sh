#!/bin/bash
#############################################
# Enable PaddleOCR (optional, higher accuracy)
#
# Run this INSIDE the backend container to install paddlepaddle + paddleocr
# and enable the `paddleocr` engine on the Taxitronic scan endpoint.
#
#   docker compose exec backend bash scripts/enable-paddleocr.sh
#
# What it does:
#   1. Detects the CPU architecture (paddlepaddle needs x86_64 CPU wheels).
#   2. Installs paddlepaddle==3.x + paddleocr==3.x.
#   3. Downloads the OCR models on first import (Spanish).
#   4. Suggests the env var to activate the engine.
#
# ARM64 note: precompiled wheels are unstable on aarch64 in Feb 2026
# (segfaults observed in the preview pod). If your VPS is ARM, skip this
# and rely on Tesseract — the pipeline degrades gracefully.
#############################################

set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ARCH=$(uname -m)

echo -e "${GREEN}[PaddleOCR] Architecture: ${ARCH}${NC}"
if [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
    echo -e "${RED}[PaddleOCR] ARM64 detected — paddlepaddle wheels are not stable here.${NC}"
    echo -e "${YELLOW}          Aborting to protect the backend. Tesseract remains active.${NC}"
    exit 1
fi

echo -e "${GREEN}[PaddleOCR] Installing paddlepaddle + paddleocr (this can take a couple of minutes)…${NC}"
pip install --no-cache-dir paddlepaddle paddleocr

echo -e "${GREEN}[PaddleOCR] Warming up (downloads models on first call)…${NC}"
python3 - <<'PY'
from paddleocr import PaddleOCR
ocr = PaddleOCR(lang="es", use_textline_orientation=True)
print("PaddleOCR ready.")
PY

echo -e "${GREEN}[PaddleOCR] Installed successfully.${NC}"
echo
echo -e "${YELLOW}Next step:${NC} enable the engine by adding this to your backend .env"
echo    "  TICKET_OCR_ENGINE=paddleocr"
echo
echo -e "${YELLOW}Then:${NC} docker compose restart backend"
