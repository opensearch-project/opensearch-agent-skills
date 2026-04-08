# Geospatial

The Geospatial plugin extends OpenSearch with spatial data types, queries, and aggregations for location-based search and analysis. It supports point, shape, and GeoJSON geometries with multiple spatial query types.

## Key Concepts

- **geo_point** — A field type that stores a single latitude/longitude coordinate. Supports distance queries, bounding box filters, and geo aggregations.
- **geo_shape** — A field type that stores arbitrary GeoJSON geometries (point, polygon, linestring, multipolygon, etc.). Supports spatial relationship queries (intersects, contains, within, disjoint).
- **xy_point / xy_shape** — Cartesian coordinate equivalents of geo_point and geo_shape for non-geographic 2D data.
- **Geo distance query** — Find documents within a specified distance from a point (e.g., "restaurants within 5km").
- **Geo bounding box query** — Find documents within a rectangular bounding box.
- **Geo shape query** — Find documents whose shapes have a specified spatial relationship with a query shape.
- **Geo aggregations** — Bucket documents by geographic criteria:
  - **geohash_grid** — Group by geohash cells at a specified precision.
  - **geotile_grid** — Group by map tiles at a specified zoom level.
  - **geo_distance** — Group by distance rings from a point.
  - **geo_bounds** — Compute the bounding box of all geo_point values.
  - **geo_centroid** — Compute the centroid of all geo_point values.
- **GeoJSON** — Standard format for encoding geographic features. Used for indexing and querying geo_shape fields.
- **Dashboards Maps** — Visualize geospatial data on interactive maps with multiple layers, custom styles, and tooltips.

## Common Use Cases

- Store locator and proximity search ("find nearest X")
- Geofencing and boundary detection
- Spatial analytics on delivery routes, fleet tracking, or IoT sensor data
- Visualizing geographic distributions on Dashboards maps

## Official Documentation

- [Geospatial overview](https://docs.opensearch.org/latest/query-dsl/geo-and-xy/index/)
- [geo_point field type](https://docs.opensearch.org/latest/field-types/supported-field-types/geo-point/)
- [geo_shape field type](https://docs.opensearch.org/latest/field-types/supported-field-types/geo-shape/)
- [Geo distance query](https://docs.opensearch.org/latest/query-dsl/geo-and-xy/geo-distance/)
- [Geo bounding box query](https://docs.opensearch.org/latest/query-dsl/geo-and-xy/geo-bounding-box/)
- [Geo shape query](https://docs.opensearch.org/latest/query-dsl/geo-and-xy/geo-shape/)
- [Geo aggregations](https://docs.opensearch.org/latest/aggregations/bucket/geohash-grid/)
- [Dashboards Maps](https://docs.opensearch.org/latest/dashboards/maps/)
