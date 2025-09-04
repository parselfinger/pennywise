from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

from pennywise.config import TXN_EMAILS_BUCKET_NAME, TXN_TABLE_NAME
from pennywise.process_txn_email import lambda_handler


@pytest.fixture
def s3_mock(setup_basic_resources, s3_client):
    """Mock S3 resource using moto."""

    email_content = MIMEText("""Hello, this is a test email.""")
    message_id = "test_message_id"
    email_content["Subject"] = "Test Subject"
    email_content["From"] = "sender@example.com"
    email_content["To"] = "recipient@example.com"

    # Upload the raw email to the mock S3 bucket
    s3_client.put_object(
        Bucket=TXN_EMAILS_BUCKET_NAME, Key=message_id, Body=email_content.as_bytes()
    )
    yield s3_client, "test_bucket", message_id


@pytest.fixture
def transaction_table(dynamodb_client):
    """Mock DynamoDB table using moto."""
    table_name = TXN_TABLE_NAME

    dynamodb_client.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "message_id", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "message_id", "AttributeType": "S"}],
        ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
    )

    yield dynamodb_client, table_name


def test_lambda_handler(s3_mock, transaction_table):
    s3, bucket_name, message_id = s3_mock
    dynamodb, table_name = transaction_table

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
        lambda_handler(event, context={})

        data = dynamodb.get_item(
            TableName=table_name, Key={"message_id": {"S": message_id}}
        )["Item"]

    assert data == {
        "message_id": {"S": "test_message_id"},
        "recipientName": {"S": "Dominic De Coco"},
        "amount": {"S": "10000.50"},
        "transactionType": {"S": "online payment"},
        "paymentMethod": {"S": "Bank transfer"},
        "date": {"S": "Jan 18, 2025"},
        "description": {"S": "One bottle of liquid luck"},
    }
