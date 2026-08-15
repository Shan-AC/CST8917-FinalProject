# Expense Approval Workflow: Dual Serverless Implementation

**Student:** Shan Jiang  
**Student Number:** 041179466  
**Course:** CST8917 — Serverless Applications  
**Project:** Assignment 2 — Compare & Contrast  
**Date:** August 14, 2026

## Workflow and Business Rules

Both versions accept an employee name, employee email, amount, category, description, and manager email. The allowed categories are `travel`, `meals`, `supplies`, `equipment`, `software`, and `other`. A valid expense below $100 is approved automatically. An expense of $100 or more waits for a manager decision. If the manager does not answer before the configured timeout, the request is auto-approved and marked as `escalated`. The employee receives the final result by email.

## Version A Summary — Durable Functions

Version A uses the Python v2 programming model. An HTTP client function starts the orchestration. The orchestrator calls separate activities for validation, result processing, and employee notification. For expenses of $100 or more, the orchestrator creates a durable timer and waits for the `ManagerDecision` external event at the same time. The first completed task decides the next branch. A second HTTP endpoint lets a manager simulation raise either an `approve` or `reject` event.

I selected this structure because the orchestrator shows the business flow clearly while the activities keep input/output work outside the deterministic orchestration code. A two-minute timeout is convenient for testing, while a production timeout could be one or two business days. The main challenge is understanding orchestration replay and making sure non-deterministic work, such as sending an email, stays inside an activity function.

## Version B Summary — Logic Apps + Service Bus

Version B uses a Service Bus queue named `expense-requests` as the entry point. A Consumption Logic App receives each message and calls the HTTP validation Azure Function. The workflow then applies the same $100 condition. For manager review, it uses the Office 365 Outlook **Send approval email** action. This action follows a webhook-style waiting pattern. Its demo timeout is set to `PT2M`. A scope configured to run after a timeout changes the result to `escalated`.

The final outcome is published to the `expense-outcomes` topic with a `status` application property. Three subscriptions use SQL filters: `status = 'approved'`, `status = 'rejected'`, and `status = 'escalated'`. The Logic App then emails the employee and completes the original queue message. The main challenge is configuring connector authentication, run-after conditions, and message properties correctly in the visual designer.

## Test Results

All six scenarios were tested successfully in both implementations. Version A was tested locally with Azure Functions Core Tools and Azurite. Version B was tested through the deployed Azure Function, Azure Service Bus, and Azure Logic App.

| Scenario | Version A | Version B | Evidence |
|---|---|---|---|
| Under $100 | Pass | Pass | Version A: `A2-completed-approved.png`; Version B: successful auto-approved Logic App run and employee email |
| Manager approves | Pass | Pass | Version A: `A5-manager-approved.png`; Version B: successful approval email and approved outcome |
| Manager rejects | Pass | Pass | Version A: `A7-manager-rejected.png`; Version B: successful rejection email and rejected outcome |
| No response / timeout | Pass | Pass | Version A: `A9-timeout-escalated.png`; Version B: successful timeout/escalated Logic App run |
| Missing fields | Pass | Pass | Version A: `A11-missing-fields.png`; Version B: validation error run for missing `description` |
| Invalid category | Pass | Pass | Version A: `A12-invalid-category.png`; Version B: validation error run for category `luxury` |

## Comparison Analysis (800–1200 words)

### 1. Development Experience

The Durable Functions version took more code, but the project structure was direct. I could follow the flow from the HTTP starter to the orchestrator and then to each activity. The important rule was to keep the orchestrator deterministic. For example, the deadline uses `context.current_utc_datetime`, not the normal system clock. Email delivery is also placed in an activity instead of the orchestrator. These rules added some learning time, but they made the responsibilities clear.

The Logic Apps version was faster for building common integration steps. The Service Bus trigger, conditions, Office 365 email, and topic output were added in the designer. I did not need to write code for every connection. However, the designer became harder to read when I added validation branches, manager decisions, and timeout recovery. Small configuration details also mattered. A wrong run-after setting could prevent the escalation scope from running even when the approval action timed out.

For debugging, Durable Functions gave me more confidence in the business rules because I could search the code and see exactly how each result was created. Logic Apps gave faster visual feedback for an individual cloud run. Overall, Logic Apps was quicker for connector setup, while Durable Functions was clearer when the workflow logic became more complex.

### 2. Testability

Version A was easier to test locally. I could run Azurite, start the Functions host, and send the six requests from `test-durable.http`. The validation helper is a normal Python function, so automated unit tests can call it without starting an orchestration. The manager endpoint also makes approval and rejection repeatable. The timeout case is slower, but a short `timeout_seconds` value makes it practical during development.

Version B required more Azure resources before the complete test could run. The validation Function can be tested locally, but the full path depends on Service Bus, Logic Apps, and an authenticated Office 365 connection. Run history is useful, but it is not the same as an automated test. A future improvement would be to deploy the workflow from infrastructure-as-code and use a test script to send queue messages and then check subscription counts. For this assignment, I used PowerShell commands to submit the six Version B test inputs. I checked the Logic App run history, employee emails, and Service Bus subscription counts to confirm that every branch worked.

### 3. Error Handling

Durable Functions provides detailed control in code. I can validate input early, return a clear validation result, and choose where an exception should stop the workflow. Durable state is checkpointed, so a long-running instance can continue after a host restart. Retry policies can also be added to specific activities, such as email delivery, without changing the approval rules. The disadvantage is that I must design these policies and understand replay behaviour.

Logic Apps has built-in retry policies and run-after options. This is convenient for HTTP, Service Bus, and email connector failures. Run history shows the inputs and outputs for every action. The difficult part is that error behaviour is spread across action settings. I must check whether the next scope runs after success, failure, skip, or timeout. For a small integration workflow this is manageable, but for a larger workflow the visual branches can hide recovery details. Durable Functions therefore gives more precise control, while Logic Apps gives easier default handling for connector errors.

### 4. Human Interaction Pattern

The Human Interaction pattern felt more natural in Durable Functions. The orchestrator waits for two tasks: an external manager event and a durable timer. `task_any` selects the first one. If the manager answers, the timer is cancelled. If the timer finishes first, the request becomes escalated. The code directly represents the business rule and does not keep a server thread running while it waits.

Logic Apps does not expose the same Durable Functions pattern. I used the Office 365 **Send approval email** action because it can wait for a response using a webhook-style connector. The action has a short demo timeout. Approval and rejection continue through normal conditions, while the escalation scope is configured to run after timeout. This works well for a Microsoft 365 environment, but it creates stronger dependence on one connector. If the business later wanted a custom approval portal, Durable Functions would be easier to extend.

### 5. Observability

Logic Apps was the easiest tool for explaining one run. The run history shows the exact branch, action status, duration, inputs, and outputs. This makes a live demonstration simple because the audience can see the workflow path. Service Bus also shows active and dead-letter message counts for the queue and subscriptions.

Durable Functions provides instance status URLs, orchestration history, logs, and Application Insights telemetry. These tools are powerful, but the complete story is spread across more views. Correlation by instance ID is important. For production, I would add structured logs with the request ID and create alerts for failed instances, notification failures, and unusually old pending approvals. Logic Apps has the better visual experience for one run, while Durable Functions gives more freedom to create custom telemetry at scale.

### 6. Cost

The estimate uses 30 days per month, 20% of expenses needing manager approval, a Consumption Functions plan, a Consumption Logic App, and a Standard Service Bus namespace because Basic does not support topics. Email licensing, taxes, log retention, data transfer, and support plans are excluded. The sample assumes about seven Function executions per expense in Version A, and about eight Logic Apps actions plus four standard connector calls per expense in Version B. Prices vary by region and agreement, so these figures must be checked in the Azure Pricing Calculator on the submission date.

| Volume | Version A: Durable Functions | Version B: Logic Apps + Service Bus |
|---|---:|---:|
| 100 expenses/day (3,000/month) | About US$0–$2/month; usage is likely inside the Functions free grant, excluding storage/email | About US$12/month; mainly the Service Bus Standard base charge plus low action/connector usage |
| 10,000 expenses/day (300,000/month) | About US$1–$8/month before email and monitoring; execution cost stays small but Durable storage operations increase | About US$220/month under the stated action/connector assumptions, before email licensing and monitoring |

At low volume, Service Bus Standard creates a fixed minimum cost for Version B. At higher volume, Logic Apps connector calls become much more visible. Durable Functions is likely cheaper for this specific code-heavy workflow, although its engineering and maintenance cost can be higher.

## Recommendation (200–300 words)

For a production expense approval system, I would choose Durable Functions as the main orchestration approach. The most important reason is not only the lower estimated platform cost. The approval rule is a long-running business process with an external decision, a timeout, and several possible outcomes. Durable Functions represents this rule clearly with an external event and a durable timer. The logic can be reviewed in source control, tested with repeatable inputs, and extended with unit and integration tests. It also gives the team detailed control over retries, idempotency, security checks, and custom telemetry.

I would still keep Service Bus as an optional entry point if the system needed load leveling or integration with other applications. I would also use a managed identity and Key Vault instead of connection strings in production. The email activity should use a production-approved provider and retry policy, and all requests should have a correlation ID.

I would choose Logic Apps instead when the workflow is mainly integration work, the organization already uses Microsoft 365 connectors, and the business process changes often. A visual workflow can help support staff understand a failed run without opening Python code. It is also a strong choice for a smaller number of requests where developer speed is more important than per-action cost. However, for this assignment's approval timer and future custom rules, Durable Functions gives a cleaner Human Interaction pattern and more confidence that complex behaviour can be tested and maintained.

## References

- Microsoft, [Durable Functions overview](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-overview)
- Microsoft, [Human interaction pattern](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-human-interaction)
- Microsoft, [Durable timers](https://learn.microsoft.com/azure/azure-functions/durable/durable-functions-timers)
- Microsoft, [Azure Service Bus queues, topics, and subscriptions](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-queues-topics-subscriptions)
- Microsoft, [Create Service Bus topics and subscriptions in the portal](https://learn.microsoft.com/azure/service-bus-messaging/service-bus-quickstart-topics-subscriptions-portal)
- Microsoft, [HTTP Webhook actions in Logic Apps](https://learn.microsoft.com/azure/connectors/connectors-native-webhook)
- Microsoft, [Logic Apps error and exception handling](https://learn.microsoft.com/azure/logic-apps/error-exception-handling)
- Microsoft Azure, [Functions pricing](https://azure.microsoft.com/pricing/details/functions/)
- Microsoft Azure, [Logic Apps pricing](https://azure.microsoft.com/pricing/details/logic-apps/)
- Microsoft Azure, [Service Bus pricing](https://azure.microsoft.com/pricing/details/service-bus/)
- Microsoft Azure, [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/)

## AI Disclosure

I used ChatGPT as an assistant during this project. It helped me suggest code organization, improve grammar, organize the comparison headings, and prepare the first version of the slide deck.


