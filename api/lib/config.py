import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ROOT_ENV)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")

BYTEPLUS_ARK_API_KEY = os.getenv("BYTEPLUS_ARK_API_KEY", "")
BYTEPLUS_ARK_BASE_URL = os.getenv("BYTEPLUS_ARK_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")
BYTEPLUS_ARK_MODEL = os.getenv("BYTEPLUS_ARK_MODEL", "deepseek-v4-flash-ga-260731")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "minimax/minimax-m3:free")

RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

# ---------------------------------------------------------------------
# LLM pricing, for run_scores.llm_cost_estimate
# ---------------------------------------------------------------------
# USD per TOKEN (not per million), keyed by the provider name that
# lib/byteplus.py records into audit_log, so a call served by OpenRouter
# is priced differently from the same prompt served by NVIDIA.
#
# Source: OpenRouter's public model catalogue, which publishes a
# machine-readable per-token rate for each model —
#   https://openrouter.ai/api/v1/models
# Observed 2026-09-02. Re-check with:
#   curl -s https://openrouter.ai/api/v1/models \
#     | jq '.data[] | select(.id|test("nemotron-3.5-lightning|deepseek-v4-flash-0731|minimax-m3")) | {id, pricing}'
#
# Read this for what it is: an ESTIMATE, and the field is named one.
# Two honest caveats:
#   1. NVIDIA and BytePlus are called on their own endpoints
#      (integrate.api.nvidia.com, ark.ap-southeast.bytepluses.com), not
#      through OpenRouter. Neither publishes a machine-readable rate for
#      these exact model ids, so the OpenRouter catalogue rate for the
#      same model is used as the reference price. It is a published rate
#      for that model, not an invoice from that vendor.
#   2. The OpenRouter model actually configured here is a ':free'
#      variant, which the catalogue prices at exactly 0 — so calls it
#      serves genuinely add nothing to the estimate.
# Tokens from a provider absent from this table are counted as unpriced
# and reported separately rather than silently treated as free.
LLM_RATES_USD_PER_TOKEN = {
    # priced as nvidia/nemotron-3.5-lightning
    "nvidia": {"prompt": 0.00000008, "completion": 0.0000002},
    # priced as deepseek/deepseek-v4-flash-0731 (the -260731 build)
    "byteplus": {"prompt": 0.000000065, "completion": 0.00000018},
    # minimax/minimax-m3:free — catalogue rate is literally 0
    "openrouter": {"prompt": 0.0, "completion": 0.0},
}
