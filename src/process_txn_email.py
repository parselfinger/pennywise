import json
import re
from email import policy
from email.parser import BytesParser
from pathlib import Path

import boto3
import google.generativeai as genai

from src.config import GEMINI_API_KEY, TXN_EMAILS_BUCKET_NAME

genai.configure(api_key=GEMINI_API_KEY)


def lambda_handler(event, context):
    s3_client = boto3.client("s3", region_name="us-east-1")
    for record in event.get("Records", []):
        ses_message = record.get("ses", {}).get("mail", {})
        message_id = ses_message.get("messageId")

        bucket_name = TXN_EMAILS_BUCKET_NAME

        raw_email = s3_client.get_object(Bucket=bucket_name, Key=message_id)[
            "Body"
        ].read()
        msg = BytesParser(policy=policy.SMTP).parsebytes(raw_email)

        model = genai.GenerativeModel("gemini-1.5-flash")

        file_path = Path(__file__).parent / "prompts/extract_transaction_details.txt"

        with open(file_path, "r") as file:
            prompt = file.read()

        prompt = prompt.replace("{msg}", str(msg))
        response = model.generate_content(prompt)

        json_match = re.search(
            r"```json\s*([\s\S]+?)\s*```", response.text, re.MULTILINE
        )
        if not json_match:
            raise ValueError("No JSON data found in response")

        cleaned_response = json_match.group(1).replace("\n", "")

        data = json.loads(cleaned_response)
        return data
