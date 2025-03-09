import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TXN_EMAILS_BUCKET_NAME = os.environ["TXN_EMAILS_BUCKET_NAME"]
