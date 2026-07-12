# Work-order learning data

The first Phase 3 data contract records:

| Field | Source | Notes |
|---|---|---|
| `machine_type` | Work order/equipment | Existing equipment model context |
| `job_type` | Dispatcher/admin | Existing service category |
| `fault_type` | Engineer | Normalized fault category for later ranking |
| `problem_description` | Dispatcher/engineer | Original symptoms |
| `error_code` | Engineer | Optional equipment/controller code |
| `environment_info` | Engineer | Temperature, access, contamination, installation conditions |
| parts and quantities | Inventory workflow | Server-attributed usage records |
| `first_time_fix` | Engineer | Whether the issue was resolved on the first visit |
| `is_rework` | Engineer | Whether this visit corrects a previous repair |
| `repair_duration_minutes` | Server | Start through engineer completion submission |
| `final_outcome` | Engineer | Repaired, temporary fix, parts required, referred, or unresolved |

The claimed engineer and registered device own field evidence. Managers can approve completion but cannot rewrite it. Pending evidence is frozen, completed evidence is immutable, and administrator corrections retain administrator attribution. Historical work orders may contain null learning fields and remain valid.
