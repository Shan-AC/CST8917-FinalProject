"""Unit tests for the shared Version A validation rules."""

from function_app import validate_expense_payload


def valid_expense(**changes):
    expense = {
        "employee_name": "Test Employee",
        "employee_email": "employee@example.com",
        "amount": 75,
        "category": "meals",
        "description": "Team lunch",
        "manager_email": "manager@example.com",
    }
    expense.update(changes)
    return expense


def test_valid_expense_is_accepted():
    result = validate_expense_payload(valid_expense())
    assert result["valid"] is True
    assert result["expense"]["amount"] == 75.0


def test_missing_fields_are_reported():
    result = validate_expense_payload({"employee_name": "Test Employee"})
    assert result["valid"] is False
    assert "Missing required fields" in result["errors"][0]


def test_invalid_category_is_rejected():
    result = validate_expense_payload(valid_expense(category="coffee"))
    assert result["valid"] is False
    assert any("Invalid category" in error for error in result["errors"])

