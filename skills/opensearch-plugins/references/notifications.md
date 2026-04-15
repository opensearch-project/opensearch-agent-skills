# Notifications

The Notifications plugin provides a centralized system for managing notification channels across OpenSearch. Other plugins (Alerting, ISM, Anomaly Detection) use Notifications to send messages when events occur.

## Key Concepts

- **Channel** — A configured notification destination. Supported channel types:
  - **Slack** — Send messages to a Slack channel via webhook URL.
  - **Email** — Send messages via SMTP (SES or custom SMTP server). Supports email groups.
  - **Webhook** — Send HTTP POST requests to a custom URL with a configurable body template.
  - **Amazon SNS** — Publish messages to an SNS topic.
  - **Amazon SES** — Send emails via SES.
  - **Microsoft Teams** — Send messages to a Teams channel via incoming webhook.
  - **Amazon Chime** — Send messages to a Chime room via webhook.
- **Notification** — A message sent through a channel. Contains a title, body, severity, and source (which plugin triggered it).
- **SMTP sender** — A configured SMTP server for email channels. Supports TLS/SSL.
- **Email group** — A named list of email recipients.

## Common Use Cases

- Sending alert notifications to Slack or Teams when monitors trigger
- Emailing stakeholders on ISM policy state transitions
- Posting anomaly detection findings to a webhook for downstream processing
- Centralizing notification configuration across all OpenSearch plugins

## Official Documentation

- [Notifications overview](https://docs.opensearch.org/latest/observing-your-data/notifications/index/)
- [Notification channels](https://docs.opensearch.org/latest/observing-your-data/notifications/channels/)
- [API reference](https://docs.opensearch.org/latest/observing-your-data/notifications/api/)
