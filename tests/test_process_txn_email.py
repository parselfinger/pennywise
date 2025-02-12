from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import boto3
import pytest
from moto import mock_aws

from src.config import TXN_EMAILS_BUCKET_NAME
from src.process_txn_email import lambda_handler


@mock_aws()
@pytest.fixture
def s3_mock(setup_basic_resources):
    """Mock S3 resource using moto."""
    s3 = boto3.client("s3", region_name="us-east-1")

    email_content = MIMEText("""Hello, this is a test email.""")
    message_id = "test_message_id"
    email_content["Subject"] = "Test Subject"
    email_content["From"] = "sender@example.com"
    email_content["To"] = "recipient@example.com"

    # Upload the raw email to the mock S3 bucket
    s3.put_object(
        Bucket=TXN_EMAILS_BUCKET_NAME, Key=message_id, Body=email_content.as_bytes()
    )
    yield s3, "test_bucket", message_id


def test_lambda_handler(s3_mock):
    s3, bucket_name, message_id = s3_mock

    event = {"Records": [{"ses": {"mail": {"messageId": message_id}}}]}

    mock_response = MagicMock()
    mock_response.text = """
    ```json\n{\n  "recipientName": "Dominic De Coco",\n  "amount": "10000.50",\n
    "transactionType": "online payment",\n  "paymentMethod": "Bank transfer",\n  "date": "Jan 18, 2025",\n
    "description": "One bottle of liquid luck"\n}\n```\n
    """

    with patch(
        "google.generativeai.GenerativeModel.generate_content",
        return_value=mock_response,
    ):
        data = lambda_handler(event, context={})
        assert data == {
            "recipientName": "Dominic De Coco",
            "amount": "10000.50",
            "transactionType": "online payment",
            "paymentMethod": "Bank transfer",
            "date": "Jan 18, 2025",
            "description": "One bottle of liquid luck",
        }
