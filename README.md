# Notion Airlock Module

A governed bridge to [Notion](https://www.notion.so). Search, read, create, and update
pages and databases in your workspace — every action reviewed, approved, and recorded
as a signed receipt through RailCall's airlock.

*Agents draft. You approve. Receipts prove.*

---

## Commands

| Command            | Type   | What it does                                              |
|--------------------|--------|-----------------------------------------------------------|
| `search`           | read   | Search pages and databases by title.                      |
| `get_page`         | read   | Retrieve a single page by ID.                             |
| `get_database`     | read   | Retrieve a database schema by ID.                         |
| `query_database`   | read   | Query a database with optional filter and sort.           |
| `create_page`      | write  | Create a page under a parent page or database.            |
| `create_database`  | write  | Create a database under a parent page.                    |
| `append_blocks`    | write  | Append content blocks (paragraphs, headings, etc.).       |
| `archive_page`     | write  | Archive (soft-delete) a page.                             |

**Read commands** execute immediately and return a signed receipt.
**Write commands** are staged by the airlock — you see a preview, approve, then the
action fires and a receipt is signed. Nothing reaches Notion without your approval.

---

## Setup

### 1. Notion Integration
* Go to **notion.so/profile/integrations** and create an internal integration.
* Copy the secret token (starts with `ntn_`).
* Share your target pages/databases in Notion via **••• → Connections**.

### 2. RailCall Studio
* Install the module and spin up the local environment:
  ```bash
  railcall market install muhamed/notion
  railcall studio
  ```
* Navigate to **Modules → Reload all** to activate the eight commands.
* Go to the **Integrations** tab and paste your token under the `notion` field.

---

## Using the commands

All commands run through Studio's command palette (or as workflow nodes, or via MCP
from Claude Desktop). There is no CLI runner — the airlock ceremony is the point.

**Example — search:**
```json
{ "query": "meeting notes", "page_size": 5 }
```

**Example — create a page:**
```json
{
  "parent_id": "255104cd-477e-808c-b279-d39ab803a7d2",
  "parent_type": "page_id",
  "title": "Sprint Review Notes"
}
```

**Example — query a database:**
```json
{
  "database_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "filter": { "property": "Status", "select": { "equals": "Done" } },
  "page_size": 20
}
```

Each call produces an Ed25519-signed receipt — verifiable offline at any time with
`railcall verify` or from Studio's **Runs** tab.

---

## What makes writes safe

* **Payload Binding:** Approvals lock to the parameter SHA-256 hash.
* **Isolated Tokens:** `NOTION_API_KEY` is saved in the vault, never logged.
* **Hermetic Runtime:** Built on Python standard library with zero dependencies.
* **Schema Enforcement:** Compliant with strict RailCall v2 spec mappings.

## Notes

- Built against Notion API version `2022-06-28`.
- Free module (`license_required: false`).

`contest:2026Q3`
