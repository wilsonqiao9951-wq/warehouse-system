# Customer onboarding and Parts List process

This runbook defines how to onboard a company without mixing its data with another customer.

## 1. Collect the customer data package

Preferred format: `.xlsx` or UTF-8 `.csv`, one header row, one part per row, no merged cells.

Required fields:

| Field | Meaning |
|---|---|
| `part_number` | Stable customer-specific SKU; must not be blank |
| `name` | Display name used by warehouse and technicians |

Recommended fields:

| Field | Meaning |
|---|---|
| `english_name` | Optional second-language name |
| `machine_type` | Supported equipment family |
| `unit` | `pcs`, `box`, `ft`, etc. |
| `default_cost` | Numeric unit cost, with currency confirmed separately |
| `safety_stock` / `min_stock` | Reorder threshold |
| `supplier` | Supplier name or supplier code |
| `image_url` | Optional product image |
| `notes` | Operational notes, substitutions, compatibility |

Generic item fields are also supported: `category`, `barcode`, `item_type`, `tracking_mode` (`none`, `batch`, or `serial`) and `is_active`. Any column beginning with `custom_` is preserved in the item's customer-specific custom field map—for example, `custom_color` or `custom_internal_code`.

Collect separately: customer legal/display name, warehouses, van assignments, users and roles, opening stock by warehouse, and desired work-order numbering policy.

## 2. Profile and map

Before import, produce a mapping report:

- Source column to OpenPartsFlow field
- Row count, blank required fields and duplicate SKUs
- Invalid quantities/costs and inconsistent units
- Proposed normalization rules
- Fields that have no destination and require a product decision

No source value should be silently discarded. The customer approves the mapping before production import.

## 3. Create an isolated organization

Create one `organization` for the customer. Users, parts, warehouses, work orders, inventory transactions, uploads and audit records inherit its `organization_id` from the authenticated user. Never accept `organization_id` from an import spreadsheet or normal API request.

## 4. Trial import

Import into a staging database first. Validate:

- Created, updated, rejected and unchanged row counts
- Duplicate handling and idempotent re-import
- Opening inventory totals by warehouse and SKU
- Sample searches in the Parts and Inventory screens
- Excel export round-trip

Store the original file, mapping version and import result as an auditable onboarding record.

### Parts Import workbench

Authorized organization administrators, managers and warehouse users can open `/parts-import`:

1. Upload an `.xlsx` file up to the configured `MAX_IMPORT_UPLOAD_BYTES` limit.
2. Review valid/error row counts, predicted creates/updates and the normalized preview.
3. Correct and re-upload files marked `invalid`; invalid batches cannot be committed.
4. Confirm a `ready` batch to upsert Parts inside the current organization.
5. Review the organization-scoped import history.

The workbook columns may appear in any order. Duplicate uploads return the existing batch, and confirming an already committed batch does not import it again. `part_number` is unique inside an organization, so different customers may use the same SKU without sharing records.

### Opening inventory workbench

After Parts and Warehouses are confirmed, open `/inventory-import` and upload an `.xlsx` containing:

| Field | Required | Meaning |
|---|---|---|
| `part_number` | Yes | Existing Part in the current organization |
| `warehouse` | Yes | Existing warehouse or Van name in the current organization |
| `quantity` | Yes | Positive whole-number opening quantity |
| `unit_cost` | No | Non-negative unit cost for the inbound transaction |
| `notes` | No | Source count, location or reconciliation note |

The preview shows current quantity, proposed opening quantity and projected quantity for each warehouse/SKU pair. Confirmation creates inbound inventory transactions; it does not overwrite or erase historical transactions. Duplicate confirmation is idempotent. Keep the physical count approval with the import batch record.

## 5. Customer acceptance and cutover

The customer signs off on the part catalog and opening balances. Then import users, warehouses, parts, stock and open work orders in that order. Run a limited pilot before broad rollout.

## Product delivery options

### Managed SaaS (recommended default)

One operated platform, one organization per customer, shared application releases, tenant-scoped database access and object storage paths. Charge setup/onboarding plus a monthly plan based on users, technicians, warehouses or work-order volume.

### Dedicated customer environment

Separate database or full deployment for customers with contractual isolation, custom retention or integration requirements. Charge a higher implementation and support fee because upgrades, monitoring and backups are duplicated.

### Self-hosted license

Only offer after installation, upgrade, backup, security patching and support responsibilities are contractually defined. This has the highest operational support burden.

## Minimum commercial readiness gate

- Formal login and account recovery
- Verified tenant isolation tests for every API domain
- Terms, privacy notice and data-processing terms
- Backup/restore test and incident response contacts
- Monitoring, audit logs and support workflow
- Defined onboarding scope, pricing, support hours and service targets
- Customer export and offboarding procedure
