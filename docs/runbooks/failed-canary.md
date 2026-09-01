# Runbook: failed or timed-out canary

1. Open the release event journal and identify `canary.observed` or
   `canary.timeout`.
2. Confirm that traffic is zero and the environment points to
   `previous_release_id`.
3. Inspect the Grafana latency/error panels and the application logs for the
   canary window.
4. Do not retry the same mutable tag. Fix the build and create a new immutable
   artifact digest and idempotency key.
5. If automatic rollback did not release the environment lock, stop new
   deployments and reconcile the database state before manual changes.

Escalate when the previous release is also unhealthy or when rollback decisions
repeat three times in fifteen minutes.

