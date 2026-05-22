# Data Retention Policy

This policy is a starting point for hosted CommerceLens customers. Adjust the
numbers by contract for Business and Enterprise plans.

## Default Retention

| Data Type | Default Retention |
| --- | ---: |
| Usage events | 24 months |
| Job and run history | 12 months |
| Extraction records | 12 months |
| Product snapshots and price history | 24 months |
| Debug HTML snapshots and screenshots | 30 days |
| Alert delivery logs | 12 months |

## Customer Controls

- Customers can request deletion of account/project data.
- Enterprise customers can negotiate shorter or longer retention windows.
- Debug artifacts should be disabled or shortened for sensitive domains.

## Deletion Process

1. Confirm the account and project identifiers.
2. Export final records if required by contract.
3. Delete jobs, runs, usage events, API keys, extraction records, snapshots, and
   debug artifacts for the scoped account/project.
4. Record the deletion request, operator, timestamp, and confirmation.
