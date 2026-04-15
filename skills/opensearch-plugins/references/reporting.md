# Reporting

The Reporting plugin generates on-demand and scheduled reports from OpenSearch Dashboards. It can export dashboards, visualizations, saved searches, and notebooks as PDF, PNG, or CSV files.

## Key Concepts

- **Report source** — The Dashboards object to export: a dashboard, visualization, saved search (Discover), or notebook.
- **Report format** — The output format: PDF (full visual rendering), PNG (single visualization), or CSV (tabular data from saved searches).
- **On-demand report** — Generate a report immediately from any supported Dashboards page via the reporting menu.
- **Scheduled report** — Create a recurring report definition that generates reports on a cron schedule.
- **Report definition** — A saved configuration specifying the source, format, schedule, and optional trigger (e.g., cron expression).
- **Report instance** — A single generated report file. Stored temporarily and available for download.
- **CSV limits** — CSV exports support up to 10,000 rows by default (configurable). Large exports may require pagination or scroll queries.

## Common Use Cases

- Scheduled daily/weekly PDF dashboards emailed to stakeholders
- Exporting saved search results as CSV for offline analysis
- Generating PNG snapshots of key visualizations for reports
- Creating compliance reports on a recurring schedule

## Official Documentation

- [Reporting overview](https://docs.opensearch.org/latest/dashboards/reporting/)
- [Creating reports](https://docs.opensearch.org/latest/dashboards/reporting/#creating-reports)
- [Scheduled reports](https://docs.opensearch.org/latest/dashboards/reporting/#creating-report-definitions)
- [API reference](https://docs.opensearch.org/latest/dashboards/reporting/#report-api)
