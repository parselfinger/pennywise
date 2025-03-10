import os

import boto3
import pytest
from moto import mock_aws

from pennywise.config import REGION, TXN_EMAILS_BUCKET_NAME


@pytest.fixture(scope="function")
def aws_credentials():
    """Mocked AWS Credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = REGION


@pytest.fixture(scope="function")
def s3_client(aws_credentials):
    with mock_aws():
        yield boto3.client("s3")


@pytest.fixture
def create_s3_bucket(s3_client):
    def create_bucket(bucket_name):
        s3_client.create_bucket(Bucket=bucket_name)

    yield create_bucket


@pytest.fixture
def setup_basic_resources(create_s3_bucket):
    create_s3_bucket(TXN_EMAILS_BUCKET_NAME)
    yield TXN_EMAILS_BUCKET_NAME


@pytest.fixture
def dynamodb_client():
    with mock_aws():
        yield boto3.client("dynamodb", region_name=REGION)
