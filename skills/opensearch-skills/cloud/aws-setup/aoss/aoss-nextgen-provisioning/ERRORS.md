# Error Handling

Companion file for the AOSS NextGen provisioning skill. Read this when any command fails.

---

## Credential Failure

If `aws sts get-caller-identity` fails, STOP immediately. Tell the user:
"AWS credentials are missing or expired. Please configure credentials and try again."

## Name Collision

If any create command fails with "ConflictException" or "already exists":
- Inform the user which resource name already exists
- Ask if they want to use a different name
- Suggest: `<name>-2` or ask for their preference

## Region Not Supported

If a command fails with "Could not connect to the endpoint URL":
- Inform the user that AOSS may not be available in that region
- Suggest supported regions: us-east-1, us-east-2, us-west-1, us-west-2, eu-west-1, eu-central-1, ap-southeast-1, ap-southeast-2, ap-northeast-1

## Invalid OCU Values

If `create-collection-group` fails with "Invalid value for maxIndexingCapacityInOCU" or similar:
- Inform the user that OCU values must be: 1, 2, 4, 8, 16, or any multiple of 16 (32, 48, 64, 80, 96)
- Ask for corrected values

## Vector Options Not Supported

If `create-collection` fails with "Providing VectorOptions during collection creation is not supported for account":
- Inform the user their account doesn't have vector acceleration enabled
- Retry without the `vectorOptions` field

## Collection Not Deletable (Still Creating)

If `delete-collection` fails with "ConflictException" and message about status not being ACTIVE/FAILED:
- The collection is still being created (NextGen: ~30s, standalone: 3-5 minutes)
- Wait 30 seconds and retry
- After 5 retries, inform user and suggest waiting a few more minutes before trying again

## Partial Failure During Provisioning

If a command fails mid-flow (e.g., collection group created but collection fails):
- Report what was successfully created
- Report what failed and the error message
- Suggest cleanup: "You can re-run with a different name, or use the Deprovision flow to clean up the partial resources."

## API Throttling

If a command fails with "ThrottlingException":
- Wait 5 seconds and retry (max 3 attempts)
- If still failing after retries, inform the user and suggest trying again in a minute

## Collection Group Not Empty on Delete

If `delete-collection-group` fails with "ValidationException" and message "has collections associated":
- The group still has active or deleting collections
- List remaining collections, delete them first, poll until gone, then retry group deletion
