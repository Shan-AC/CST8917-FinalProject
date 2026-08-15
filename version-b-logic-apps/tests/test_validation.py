"""Unit tests for the validation Function used by Version B."""

from function_app import validate_payload


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
    result = validate_payload(valid_expense())
    assert result["valid"] is True


def test_invalid_category_is_rejected():
    result = validate_payload(valid_expense(category="coffee"))
    assert result["valid"] is False
    assert any("Invalid category" in error for error in result["errors"])

