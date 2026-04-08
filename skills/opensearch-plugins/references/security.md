# Security

The Security plugin provides authentication, authorization, encryption, and audit logging for OpenSearch. It supports a wide range of identity backends and enables fine-grained access control down to the field and document level.

## Key Concepts

- **Authentication backends** — Support for internal user database, LDAP/Active Directory, SAML, OpenID Connect (OIDC), Kerberos, HTTP basic auth, proxy-based auth, and JSON web tokens (JWT).
- **Roles** — Define permissions for cluster-level operations, index-level operations, and document/field-level access. Roles are mapped to users or backend roles.
- **Role mapping** — Associates OpenSearch roles with users, backend roles, or hosts. Backend roles are typically group memberships from LDAP or SAML.
- **Action groups** — Named collections of permissions for convenience (e.g., `crud`, `read`, `search`, `manage`).
- **Field-level security (FLS)** — Restrict which fields a role can see in a given index.
- **Document-level security (DLS)** — Restrict which documents a role can see using a query filter.
- **Audit logging** — Log authentication attempts, permission grants/denials, and index operations. Supports output to internal index or external destinations.
- **TLS/SSL** — Encrypts transport (node-to-node) and REST (client-to-node) traffic. Required for production deployments.
- **Security configuration** — Stored in a special `.opendistro_security` index. Managed via `securityadmin.sh` or the REST API.
- **Tenants** — Isolated workspaces in OpenSearch Dashboards. Users can have private tenants and access shared global tenants.

## Common Use Cases

- Setting up SAML or OIDC single sign-on for Dashboards
- Implementing multi-tenant access with document-level security
- Restricting sensitive fields (PII, credentials) with field-level security
- Configuring LDAP group-based access control
- Enabling audit logging for compliance

## Tutorials

- [Getting started with security](https://docs.opensearch.org/latest/security/getting-started/) — Initial security configuration walkthrough
- [Security configuration guide](https://docs.opensearch.org/latest/security/configuration/index/) — Detailed configuration reference

## Official Documentation

- [Security overview](https://docs.opensearch.org/latest/security/index/)
- [Authentication backends](https://docs.opensearch.org/latest/security/authentication-backends/authc-index/)
- [Access control](https://docs.opensearch.org/latest/security/access-control/index/)
- [Roles](https://docs.opensearch.org/latest/security/access-control/users-roles/)
- [Field-level security](https://docs.opensearch.org/latest/security/access-control/field-level-security/)
- [Document-level security](https://docs.opensearch.org/latest/security/access-control/document-level-security/)
- [Audit logging](https://docs.opensearch.org/latest/security/audit-logs/index/)
- [TLS configuration](https://docs.opensearch.org/latest/security/configuration/tls/)
- [API reference](https://docs.opensearch.org/latest/security/access-control/api/)
