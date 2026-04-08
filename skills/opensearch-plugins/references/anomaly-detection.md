# Anomaly Detection

The Anomaly Detection plugin automatically identifies unusual patterns in streaming data using the Random Cut Forest (RCF) algorithm. It runs as a background job on the OpenSearch cluster and can detect anomalies in real time or over historical data.

## Key Concepts

- **Detector** — A configuration that defines what data to monitor, which features to extract, and how often to check. Each detector targets one index (or index pattern) and can have one or more features.
- **Feature** — A numeric aggregation (e.g., `avg`, `sum`, `count`, `max`) computed over a field. The detector feeds feature values into the RCF model.
- **Random Cut Forest (RCF)** — An unsupervised machine learning algorithm for anomaly scoring. Higher anomaly grades indicate more unusual data points.
- **Anomaly grade** — A value between 0 and 1 indicating how anomalous a data point is. A grade of 0 means normal; values closer to 1 indicate strong anomalies.
- **Confidence** — A value between 0 and 1 indicating how confident the model is. Confidence increases as the model ingests more data.
- **Real-time detection** — The detector runs at a configured interval (e.g., every 5 minutes) and scores the latest data.
- **Historical detection** — Run the detector over a past time range to find anomalies in historical data.
- **High-cardinality detection** — Split detection by a categorical field (e.g., detect anomalies per host, per region) using the `category_field` option.

## Common Use Cases

- Monitoring application metrics for sudden spikes or drops
- Detecting unusual traffic patterns in web server logs
- Identifying infrastructure anomalies (CPU, memory, disk) per host
- Spotting revenue or transaction anomalies in business data

## Guides

- [Managing anomalies](https://docs.opensearch.org/latest/observing-your-data/ad/managing-anomalies/) — Creating and managing detectors via Dashboards
- [Result mapping](https://docs.opensearch.org/latest/observing-your-data/ad/result-mapping/) — Understanding anomaly result indices and fields

## Official Documentation

- [Anomaly Detection overview](https://docs.opensearch.org/latest/observing-your-data/ad/index/)
- [API reference](https://docs.opensearch.org/latest/observing-your-data/ad/api/)
- [Security configuration](https://docs.opensearch.org/latest/observing-your-data/ad/security/)
- [Settings reference](https://docs.opensearch.org/latest/observing-your-data/ad/settings/)
- [Dashboards integration](https://docs.opensearch.org/latest/observing-your-data/ad/dashboards-anomaly-detection/)
