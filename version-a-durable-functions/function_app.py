"""CST8917 Assignment 2 - Version A: Azure Durable Functions.

AI disclosure: Generative AI helped prepare the initial file structure,
comments, and error-handling suggestions. The student must review, test, and
be able to explain every part before submission.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import timedelta
from typing import Any

import azure.durable_functions as df
import azure.functions as func
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail


app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

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


def _json_response(payload: dict[str, Any], status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, indent=2),
        status_code=status_code,
        mimetype="application/json",
    )


def validate_expense_payload(expense: dict[str, Any]) -> dict[str, Any]:
    """Pure validation helper so the business rules can be unit tested."""
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


@app.route(route="expenses/start", methods=["POST"])
@app.durable_client_input(client_name="client")
async def start_expense(req: func.HttpRequest, client: df.DurableOrchestrationClient):
    """HTTP client function that starts a new expense orchestration."""
    try:
        payload = req.get_json()
    except ValueError:
        return _json_response({"error": "Request body must be valid JSON."}, 400)

    if not isinstance(payload, dict):
        return _json_response({"error": "Request body must be a JSON object."}, 400)

    # Two minutes is convenient for a classroom demo. Use a much longer value in production.
    payload.setdefault("timeout_seconds", int(os.getenv("APPROVAL_TIMEOUT_SECONDS", "120")))
    instance_id = await client.start_new("expense_orchestrator", None, payload)
    logging.info("Started expense orchestration %s", instance_id)
    return client.create_check_status_response(req, instance_id)


@app.route(route="expenses/{instance_id}/decision", methods=["POST"])
@app.durable_client_input(client_name="client")
async def manager_decision(
    req: func.HttpRequest,
    client: df.DurableOrchestrationClient,
):
    """HTTP endpoint that simulates a manager approval or rejection."""
    instance_id = req.route_params.get("instance_id", "")
    try:
        body = req.get_json()
    except ValueError:
        return _json_response({"error": "Request body must be valid JSON."}, 400)

    decision = str(body.get("decision", "")).strip().lower()
    if decision not in {"approve", "reject"}:
        return _json_response({"error": "decision must be approve or reject."}, 400)

    status = await client.get_status(instance_id)
    if status is None:
        return _json_response({"error": "Orchestration instance was not found."}, 404)

    await client.raise_event(
        instance_id,
        "ManagerDecision",
        {"decision": decision, "comment": str(body.get("comment", ""))},
    )
    return _json_response(
        {
            "message": "Manager decision event was sent.",
            "instance_id": instance_id,
            "decision": decision,
        },
        202,
    )


@app.orchestration_trigger(context_name="context")
def expense_orchestrator(context: df.DurableOrchestrationContext):
    """Coordinates validation, approval, timeout, processing, and notification."""
    request = context.get_input()
    validation = yield context.call_activity("validate_expense", request)

    if not validation["valid"]:
        result = {
            "status": "validation_error",
            "reason": "; ".join(validation["errors"]),
            "expense": validation["expense"],
        }
        notification = yield context.call_activity("send_notification", result)
        result["notification"] = notification
        return result

    expense = validation["expense"]
    if expense["amount"] < 100:
        result = yield context.call_activity(
            "process_expense",
            {
                "expense": expense,
                "status": "approved",
                "reason": "Automatically approved because the amount is under $100.",
            },
        )
    else:
        timeout_seconds = max(5, int(request.get("timeout_seconds", 120)))
        deadline = context.current_utc_datetime + timedelta(seconds=timeout_seconds)
        timeout_task = context.create_timer(deadline)
        decision_task = context.wait_for_external_event("ManagerDecision")
        winner = yield context.task_any([decision_task, timeout_task])

        if winner == decision_task:
            timeout_task.cancel()
            manager_result = decision_task.result

            # Durable Functions may return the external event as a JSON string.
            if isinstance(manager_result, str):
                try:
                    manager_result = json.loads(manager_result)
                except json.JSONDecodeError:
                    manager_result = {"decision": manager_result}

            if not isinstance(manager_result, dict):
                manager_result = {}

            approved = manager_result.get("decision") == "approve"
            result = yield context.call_activity(
                "process_expense",
                {
                    "expense": expense,
                    "status": "approved" if approved else "rejected",
                    "reason": manager_result.get("comment")
                    or ("Approved by manager." if approved else "Rejected by manager."),
                },
            )
        else:
            result = yield context.call_activity(
                "process_expense",
                {
                    "expense": expense,
                    "status": "escalated",
                    "reason": "No manager response arrived before the timeout; auto-approved and flagged.",
                },
            )

    notification = yield context.call_activity("send_notification", result)
    result["notification"] = notification
    return result


@app.activity_trigger(input_name="expense")
def validate_expense(expense):
    """Activity: apply the common validation rules."""
    return validate_expense_payload(expense)


@app.activity_trigger(input_name="payload")
def process_expense(payload):
    """Activity: create the final result object."""
    expense = payload["expense"]
    return {
        "status": payload["status"],
        "reason": payload["reason"],
        "employee_name": expense["employee_name"],
        "employee_email": expense["employee_email"],
        "manager_email": expense["manager_email"],
        "amount": expense["amount"],
        "category": expense["category"],
        "description": expense["description"],
    }


@app.activity_trigger(input_name="result")
def send_notification(result):
    """Activity: email the employee through SendGrid, or log in local demo mode."""
    employee_email = result.get("employee_email") or result.get("expense", {}).get(
        "employee_email"
    )
    status = result["status"]
    reason = result.get("reason", "")
    subject = f"Expense request result: {status.replace('_', ' ').title()}"
    body = (
        f"Hello {result.get('employee_name', result.get('expense', {}).get('employee_name', 'employee'))},\n\n"
        f"Your expense request status is: {status}.\n"
        f"Reason: {reason}\n\n"
        "This message was generated by the CST8917 expense approval demo."
    )

    email_mode = os.getenv("EMAIL_MODE", "console").lower()
    api_key = os.getenv("SENDGRID_API_KEY", "")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "")
    if email_mode != "sendgrid" or not api_key or not from_email:
        logging.info("EMAIL_MODE=console | To=%s | Subject=%s | %s", employee_email, subject, body)
        return {"delivery": "console", "to": employee_email}

    try:
        message = Mail(
            from_email=from_email,
            to_emails=employee_email,
            subject=subject,
            plain_text_content=body,
        )
        response = SendGridAPIClient(api_key).send(message)
        return {"delivery": "sendgrid", "status_code": response.status_code, "to": employee_email}
    except Exception as exc:  # Keep the business result visible even if email delivery fails.
        logging.exception("Email delivery failed")
        return {"delivery": "failed", "to": employee_email, "error": str(exc)}

