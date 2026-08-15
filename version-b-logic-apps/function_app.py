"""CST8917 Assignment 2 - Version B support functions.

The Logic App performs orchestration. This Function App provides the required
validation endpoint and an HTTP ingestion endpoint for repeatable testing.

AI disclosure: Generative AI helped prepare the initial structure, comments,
and validation edge cases. The student must review and test the final code.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any

import azure.functions as func
from azure.servicebus import ServiceBusClient, ServiceBusMessage


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)

VALID_CATEGORIES = {
    "travel",
    "meals",
    "supplies",
    "equipment",
    "software",
    "other",
}
REQUIRED_FIELDS = {
    "employee_name",
    "employee_email",
    "amount",
    "category",
    "description",
    "manager_email",
}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _response(payload: dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, indent=2),
        status_code=status_code,
        mimetype="application/json",
    )


def validate_payload(expense: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    missing = sorted(
        field
        for field in REQUIRED_FIELDS
        if field not in expense or expense[field] is None or str(expense[field]).strip() == ""
    )
    if missing:
        errors.append(f"Missing required fields: {', '.join(missing)}")

    normalized = dict(expense)
    if "category" in normalized and normalized["category"] is not None:
        normalized["category"] = str(normalized["category"]).strip().lower()
        if normalized["category"] not in VALID_CATEGORIES:
            errors.append(
                "Invalid category. Use travel, meals, supplies, equipment, software, or other."
            )

    if "amount" in normalized and normalized["amount"] not in (None, ""):
        try:
            normalized["amount"] = round(float(normalized["amount"]), 2)
            if normalized["amount"] < 0:
                errors.append("Amount must be zero or greater.")
        except (TypeError, ValueError):
            errors.append("Amount must be a number.")

    for email_field in ("employee_email", "manager_email"):
        value = normalized.get(email_field)
        if value and not EMAIL_PATTERN.match(str(value).strip()):
            errors.append(f"{email_field} must be a valid email address.")

    return {"valid": not errors, "errors": errors, "expense": normalized}


@app.route(route="validate-expense", methods=["POST"])
def validate_expense(req: func.HttpRequest) -> func.HttpResponse:
    """Called by the Logic App after it receives a Service Bus message."""
    try:
        body = req.get_json()
    except ValueError:
        return _response({"valid": False, "errors": ["Request body must be valid JSON."]}, 400)

    if not isinstance(body, dict):
        return _response({"valid": False, "errors": ["Request body must be a JSON object."]}, 400)
    return _response(validate_payload(body))


@app.route(route="submit-expense", methods=["POST"])
def submit_expense(req: func.HttpRequest) -> func.HttpResponse:
    """Places a test expense request on the incoming Service Bus queue."""
    try:
        body = req.get_json()
    except ValueError:
        return _response({"error": "Request body must be valid JSON."}, 400)

    if not isinstance(body, dict):
        return _response({"error": "Request body must be a JSON object."}, 400)

    body.setdefault("request_id", str(uuid.uuid4()))
    connection_string = os.getenv("SERVICE_BUS_CONNECTION")
    queue_name = os.getenv("EXPENSE_QUEUE_NAME", "expense-requests")
    if not connection_string:
        return _response(
            {"error": "SERVICE_BUS_CONNECTION is not configured.", "request": body},
            500,
        )

    with ServiceBusClient.from_connection_string(connection_string) as client:
        with client.get_queue_sender(queue_name=queue_name) as sender:
            sender.send_messages(
                ServiceBusMessage(
                    json.dumps(body),
                    content_type="application/json",
                    message_id=body["request_id"],
                )
            )

    return _response(
        {"message": "Expense request was queued.", "queue": queue_name, "request": body},
        202,
    )


@app.route(route="health", methods=["GET"])
def health(req: func.HttpRequest) -> func.HttpResponse:
    return _response({"status": "healthy", "service": "version-b-support-functions"})

