import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ROOT_ENV)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
BYTEPLUS_ARK_API_KEY = os.getenv("BYTEPLUS_ARK_API_KEY", "")
BYTEPLUS_ARK_BASE_URL = os.getenv("BYTEPLUS_ARK_BASE_URL", "https://ark.ap-southeast.bytepluses.com/api/v3")
BYTEPLUS_ARK_MODEL = os.getenv("BYTEPLUS_ARK_MODEL", "deepseek-v4-flash-260425")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
