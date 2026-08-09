# OpenPartsFlow Pilot Runbook (Internal)

## 1) Pilot Goal

Run a controlled internal pilot to validate that OpenPartsFlow can replace AppSheet in real daily operations with low risk.

Pilot scope:
- 1 to 2 technicians only
- 3 pilot days
- Core workflows only (work order execution, parts usage, inventory linkage, manager review)

Pilot objective:
- Prove operational usability and data reliability before company-wide rollout.

---

## 2) Pre-Launch Checklist

Before Day 1, confirm all items:

- [ ] Backend service is running and reachable (`/docs` available)
- [ ] Frontend service is running and reachable
- [ ] `RBAC_ENFORCE` is configured as planned for pilot (recommended: `true`)
- [ ] Required user accounts are created and role-assigned
- [ ] At least 1 warehouse and 1 technician van warehouse are configured
- [ ] Parts master data is imported and validated
- [ ] Opening inventory quantities are loaded
- [ ] Work orders for pilot days are loaded/imported
- [ ] Excel export/import endpoints tested
- [ ] Pilot support owner assigned (who responds to issues)
- [ ] Daily backup/export owner assigned
- [ ] AppSheet/Google Sheets integration is active and its parity contract is `ready`
- [ ] Canonical snapshot export procedure is rehearsed without customer names, descriptions, media, or credentials
- [ ] Administrator records a password-confirmed parallel reconciliation and resolves every difference

---

## 3) Required Test Accounts

Create and verify these accounts before pilot:

- [ ] `admin` (full control)
- [ ] `manager` (operations + profit/performance view)
- [ ] `warehouse` (inventory operations only)
- [ ] `technician` (assigned jobs + own van only)

Recommended naming:
- `pilot-admin`
- `pilot-manager`
- `pilot-wh-01`
- `pilot-tech-01`
- `pilot-tech-02` (optional if running 2-tech pilot)

---

## 4) Role-Based Test Scripts

### 4.1 Technician Daily Job Flow

1. Sign in with the technician's own email/password on the registered phone
2. Open the shared work-order pool; confirm other engineers' progress is read-only
3. Claim an available work order on the registered phone
4. Open `Today` or `My Jobs` and select the claimed work order
5. Tap `Start Job` (status should become `IN_PROGRESS`)
6. Add job status updates
7. Add parts used
8. Upload QC pictures
9. Add returned equipment (if applicable)
10. Tap `Complete Job` with the current account password
11. Verify exact engineer/device attribution and the post-completion lock

Expected result:
- Same-organization jobs and progress are visible, but only the active claimant
  on the bound device can modify field data
- All actions saved with timestamps
- No post-completion edits allowed

### 4.2 Manager Work Order Review

1. Open `Work Orders`  
2. Apply filters (technician/status/date/city/job type/search)  
3. Review selected jobs  
4. Verify revenue/labor cost values  
5. Open `Reports` and check abnormal usage highlights  
6. Verify profit view available on relevant jobs

Expected result:
- Filters work and persist after refresh
- Profit and anomalies are visible to manager only

### 4.3 Warehouse Inventory Transfer

1. Sign in with the warehouse employee's own email/password
2. Open `Inventory`  
3. Review stock and low stock alerts  
4. Create transfer transaction (main -> van / van -> main)  
5. Verify inventory balances updated

Expected result:
- Transfers succeed only with valid stock
- Balances reconcile with transaction ledger

### 4.4 Admin User/Permission Check

1. Verify user accounts and roles  
2. Validate restricted access per role  
3. Confirm audit logs capture key actions  
4. Confirm pilot checklist page health metrics are available
5. Open `Parallel Run`, verify the source revision, submit the controlled
   canonical snapshot, and review work-order/part-usage/inventory differences

Expected result:
- RBAC boundaries enforced
- No unauthorized access to sensitive data
- Evidence is tenant-scoped and the raw source snapshot/password is not retained

---

## 5) Daily Pilot Operating Procedure

### Morning Dispatch
- Manager loads/reviews today's work orders
- Assigns technician(s)
- Confirms route priorities

### Technician Job Execution
- Technician starts each assigned job
- Updates status during execution

### Parts Usage
- Technician records parts used from van inventory
- System deducts inventory automatically

### QC Picture Upload
- Technician uploads proof images during/after work

### Completion Review
- Technician completes job
- Manager verifies completion quality and missing fields

### Inventory Review
- Warehouse reviews low stock and transfer needs
- Reconciles key transaction records

### Abnormal Alert Review
- Manager checks abnormal usage report daily
- Investigates flagged work orders

### Parallel Reconciliation
- Administrator exports the canonical AppSheet/Google Sheets snapshot for the
  agreed observation window
- Records the comparison under `Parallel Run` with current-account password
- Manager reviews the append-only counts and bounded differences
- Any mismatch blocks cutover until explained, corrected, and re-run

---

## 6) Rollback Plan

### When to Stop Pilot

Stop pilot immediately if any of these occur:
- Repeated inventory mismatches with no clear fix
- Critical RBAC breach (unauthorized data exposure)
- Frequent job completion failures blocking operations
- Data integrity issues affecting daily dispatch

### How to Return to AppSheet

1. Announce pilot pause and freeze new OpenPartsFlow entries  
2. Resume AppSheet as primary system  
3. Keep OpenPartsFlow read-only for investigation  
4. Log incidents and root causes before retry

### Data to Export Before Rollback

- Work orders export (`/api/export/work-orders.xlsx`)
- Inventory export (`/api/export/inventory.xlsx`)
- Parts export (`/api/export/parts.xlsx`)
- Audit logs (`/api/audit-logs`)
- Abnormal usage report (`/api/reports/abnormal-usage`)

---

## 7) Known Risks

- Inventory mismatch between transactions and expected physical stock
- Shared credentials, stale sessions, or an unregistered engineer phone
- Mobile usability friction in field conditions
- Incomplete job data before completion
- Duplicate work orders due to import/manual entry overlap

Risk controls:
- Daily reconciliation checklist
- Role/account quick guide card
- Mandatory completion validation checklist
- WO numbering policy enforcement

---

## 8) Training Checklist

### Technician Training
- [ ] Start/Complete job flow
- [ ] Status updates
- [ ] Parts usage recording
- [ ] QC image upload
- [ ] Returned equipment logging
- [ ] Van inventory lookup

### Manager Training
- [ ] Dispatch and assignment
- [ ] Filter usage in work orders
- [ ] Profit and abnormal usage review
- [ ] Completion quality check
- [ ] Pilot checklist monitoring

### Warehouse Training
- [ ] Inventory balance review
- [ ] Transfer transactions
- [ ] Low stock handling
- [ ] Reconciliation workflow

---

## 9) Pilot Success Criteria

Record role training/UAT and issue evidence in `/pilot-checklist`; the Markdown
boxes below are operating prompts, not the authoritative sign-off record.

Pilot is considered successful if all are met:

- [ ] 90%+ work orders completed in system
- [ ] Parts usage recorded correctly
- [ ] Manager can review profit
- [ ] Warehouse can reconcile inventory
- [ ] No critical data loss

Additional recommended target:
- [ ] No unresolved severity-1 issue at end of pilot day 3
- [ ] Latest controlled parallel reconciliation is `matched`
- [ ] Customer-specific formulas, Bots, security filters, attachments, and scheduled reports have separate signed acceptance evidence

---

## 10) Go/No-Go Decision Checklist

After 3-day pilot, complete decision checklist:

- [ ] Success criteria met
- [ ] No critical RBAC/security issue
- [ ] Inventory discrepancies within acceptable threshold
- [ ] Technician usability feedback acceptable
- [ ] Manager reporting accuracy acceptable
- [ ] Rollback readiness documented
- [ ] Support plan ready for wider rollout
- [ ] Latest Pilot Checklist uses tenant-scoped counts and links to current parallel-run evidence

Decision:
- **Go**: Expand to next technician group / broader deployment
- **No-Go**: Continue AppSheet primary flow, fix gaps, re-run pilot

The organization administrator records the internal decision in Pilot
Governance. `Go` is server-blocked until every operational role has passed
training and UAT, no sev1 issue remains open, and a matched parallel
reconciliation exists within the campaign window. Customer-specific and legal
acceptance remains separate.

---

## Pilot Recommendation

Run with **1 to 2 technicians first** (not full company).  
Operate for **3 days**, review daily outcomes, then decide formal cutover.
