import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from pennywise.generate_monthly_reports import (
    DecimalEncoder,
    extract_month_from_date,
    generate_monthly_report,
    parse_amount,
)


class TestParseAmount:
    """Test the parse_amount function."""

    def test_parse_naira_amount(self):
        assert parse_amount("₦123.45") == 123.45
        assert parse_amount("₦1,234.56") == 1234.56
        assert parse_amount("₦0.99") == 0.99
        assert parse_amount("₦50000") == 50000.0

    def test_parse_dollar_amount(self):
        assert parse_amount("$123.45") == 123.45
        assert parse_amount("$1,234.56") == 1234.56
        assert parse_amount("$0.99") == 0.99

    def test_parse_pound_amount(self):
        assert parse_amount("£50.00") == 50.0
        assert parse_amount("£1,000") == 1000.0

    def test_parse_euro_amount(self):
        assert parse_amount("€25.50") == 25.5
        assert parse_amount("€2,500") == 2500.0

    def test_parse_plain_number(self):
        assert parse_amount("123.45") == 123.45
        assert parse_amount("1000") == 1000.0

    def test_parse_empty_or_none(self):
        assert parse_amount("") == 0.0
        assert parse_amount(None) == 0.0

    def test_parse_invalid_string(self):
        assert parse_amount("invalid") == 0.0
        assert parse_amount("abc123def") == 0.0


class TestExtractMonthFromDate:
    """Test the extract_month_from_date function."""

    def test_iso_format(self):
        assert extract_month_from_date("2024-01-15") == "2024-01"
        assert extract_month_from_date("2023-12-31") == "2023-12"

    def test_slash_formats(self):
        assert extract_month_from_date("15/01/2024") == "2024-01"
        assert extract_month_from_date("01/15/2024") == "2024-01"
        assert extract_month_from_date("2024/01/15") == "2024-01"

    def test_dash_formats(self):
        assert extract_month_from_date("15-01-2024") == "2024-01"
        assert extract_month_from_date("01-15-2024") == "2024-01"

    def test_invalid_dates(self):
        assert extract_month_from_date("invalid") is None
        assert extract_month_from_date("") is None
        assert extract_month_from_date(None) is None

    def test_edge_cases(self):
        assert extract_month_from_date("2024-02-29") == "2024-02"  # Leap year
        assert extract_month_from_date("2023-02-28") == "2023-02"


class TestDecimalEncoder:
    """Test the DecimalEncoder class."""

    def test_decimal_encoding(self):
        encoder = DecimalEncoder()
        assert encoder.default(Decimal("123.45")) == 123.45
        assert encoder.default(Decimal("0")) == 0.0

    def test_other_types(self):
        encoder = DecimalEncoder()
        with pytest.raises(TypeError):
            encoder.default("string")


class TestGenerateMonthlyReport:
    """Test the generate_monthly_report function."""

    @pytest.fixture
    def mock_table(self):
        """Create a mock DynamoDB table with sample data."""
        table = Mock()

        sample_items = [
            {
                "date": "2025-08-15",
                "amount": "100.00",
                "transactionType": "debit",
                "category": "Food",
                "merchant": "Grocery Store",
                "description": "Weekly groceries",
                "paymentMethod": "card",
            },
            {
                "date": "2025-08-20",
                "amount": "50.00",
                "transactionType": "debit",
                "category": "Transport",
                "merchant": "Gas Station",
                "description": "Fuel",
                "paymentMethod": "card",
            },
            {
                "date": "2025-08-25",
                "amount": "2000.00",
                "transactionType": "credit",
                "category": "Salary",
                "merchant": "Employer",
                "description": "Monthly salary",
                "paymentMethod": "transfer",
            },
            {
                "date": "2025-08-01",
                "amount": "75.00",
                "transactionType": "debit",
                "category": "Entertainment",
                "merchant": "Movie Theater",
                "description": "Movie tickets",
                "paymentMethod": "card",
            },
        ]

        table.scan.return_value = {"Items": sample_items, "Count": len(sample_items)}

        return table

    @pytest.fixture
    def temp_output_dir(self):
        """Create a temporary directory for test outputs."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @patch("pennywise.generate_monthly_reports.datetime")
    def test_generate_monthly_report(self, mock_datetime, mock_table, temp_output_dir):
        """Test the complete monthly report generation."""

        mock_datetime.now.return_value = datetime(2025, 9, 1)
        mock_datetime.strptime = datetime.strptime
        mock_datetime.strftime = datetime.strftime

        generate_monthly_report(mock_table, temp_output_dir)

        output_path = Path(temp_output_dir)

        assert (output_path / "transaction_report_2025-08.pdf").exists()

        # Check that PDF file is not empty (basic file size check)
        assert (output_path / "transaction_report_2025-08.pdf").stat().st_size > 0

    @patch("pennywise.generate_monthly_reports.datetime")
    def test_generate_monthly_report_with_pagination(
        self, mock_datetime, temp_output_dir
    ):
        """Test report generation with paginated DynamoDB results."""
        mock_datetime.now.return_value = datetime(2025, 9, 1)
        mock_datetime.strptime = datetime.strptime
        mock_datetime.strftime = datetime.strftime

        table = Mock()

        # Mock paginated responses for the previous month (August 2025)
        table.scan.side_effect = [
            {
                "Items": [
                    {
                        "date": "2025-08-15",
                        "amount": "100.00",
                        "transactionType": "debit",
                        "category": "Food",
                        "merchant": "Grocery Store",
                        "description": "Grocery purchase",
                        "paymentMethod": "card",
                    }
                ],
                "LastEvaluatedKey": "key1",
            },
            {
                "Items": [
                    {
                        "date": "2025-08-20",
                        "amount": "50.00",
                        "transactionType": "debit",
                        "category": "Transport",
                        "merchant": "Gas Station",
                        "description": "Fuel purchase",
                        "paymentMethod": "card",
                    }
                ]
            },
        ]

        generate_monthly_report(table, temp_output_dir)

        output_path = Path(temp_output_dir)

        aug_pdf = output_path / "transaction_report_2025-08.pdf"
        assert aug_pdf.exists(), "August PDF report not created"
        assert aug_pdf.stat().st_size > 0, "August PDF report is empty"

    @patch("pennywise.generate_monthly_reports.datetime")
    def test_generate_monthly_report_with_pdf_output_only(
        self, mock_datetime, mock_table, temp_output_dir
    ):
        """Test the complete monthly report generation and verify PDF files."""
        mock_datetime.now.return_value = datetime(2025, 9, 1)
        mock_datetime.strptime = datetime.strptime
        mock_datetime.strftime = datetime.strftime

        generate_monthly_report(mock_table, temp_output_dir)

        # Check that files were created
        output_path = Path(temp_output_dir)

        # Check that PDF file was created for the previous month only
        aug_pdf = output_path / "transaction_report_2025-08.pdf"

        # Verify the PDF file exists
        assert aug_pdf.exists(), "August PDF report not created"
        assert aug_pdf.stat().st_size > 0, "August PDF report is empty"

        # Verify it is an actual PDF file (check first few bytes)
        with open(aug_pdf, "rb") as f:
            header = f.read(4)
            assert header == b"%PDF", f"{aug_pdf} is not a valid PDF file"


if __name__ == "__main__":
    pytest.main([__file__])
