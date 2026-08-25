"""Handlers for the muhamed/notion module.

Each top-level function matches a command declared in module.json.
The RailCall runtime wraps every call in the airlock:
  input validation -> preview -> approve (for side-effect commands)
  -> execute -> signed receipt.

The handler only returns data; it never calls the airlock directly.

Auth: declared as api_key with env_var NOTION_API_KEY in module.json.
The RailCall runtime injects the token from the local vault (configured
via Studio's Integrations tab) into the handler context.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionError(Exception):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def to_dict(self):
        return {
            "object": "error",
            "code": self.code,
            "message": self.message,
            "status": self.status,
        }


def _get_token(context):
    if isinstance(context, dict):
        for source in (context.get("env"), context.get("credentials")):
            if isinstance(source, dict):
                token = source.get("NOTION_API_KEY")
                if isinstance(token, str) and token.strip():
                    return token.strip()

    token = os.environ.get("NOTION_API_KEY")
    return token.strip() if isinstance(token, str) and token.strip() else None


def _request(token, method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        f"{NOTION_API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read().decode("utf-8")
            if not payload:
                return {}
            try:
                return json.loads(payload)
            except json.JSONDecodeError as error:
                raise NotionError(
                    "invalid_response",
                    "Notion returned an invalid JSON response.",
                    response.status,
                ) from error
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            response = json.loads(response_body)
        except json.JSONDecodeError:
            response = {}
        message = response.get("message", response_body) if isinstance(response, dict) else response_body
        code = response.get("code", "http_error") if isinstance(response, dict) else "http_error"
        raise NotionError(code, message, error.code) from error
    except urllib.error.URLError as error:
        raise NotionError("network_error", str(error.reason)) from error


def _run(operation, inputs, context):
    if not isinstance(inputs, dict):
        return NotionError("validation_error", "Command inputs must be an object.", 400).to_dict()

    token = _get_token(context)
    if not token:
        return NotionError(
            "auth_missing",
            "Notion API key is not configured. Add it in Studio's Integrations tab.",
        ).to_dict()

    try:
        return operation(token, inputs)
    except NotionError as error:
        return error.to_dict()


def _required_string(inputs, name, allow_empty=False):
    value = inputs.get(name)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise NotionError("validation_error", f"'{name}' must be a non-empty string.", 400)
    return value


def _resource_id(inputs, name):
    return urllib.parse.quote(_required_string(inputs, name).strip(), safe="")


def _page_size(inputs):
    value = inputs.get("page_size", 10)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise NotionError("validation_error", "'page_size' must be an integer from 1 to 100.", 400)
    return value


def _optional_object(inputs, name):
    value = inputs.get(name)
    if value is not None and not isinstance(value, dict):
        raise NotionError("validation_error", f"'{name}' must be an object.", 400)
    return value


def _required_object(inputs, name):
    value = _optional_object(inputs, name)
    if value is None:
        raise NotionError("validation_error", f"'{name}' is required.", 400)
    return value


def _required_array(inputs, name):
    value = inputs.get(name)
    if not isinstance(value, list):
        raise NotionError("validation_error", f"'{name}' must be an array.", 400)
    return value


def _extract_title(resource):
    if resource.get("object") == "database":
        title = resource.get("title", [])
    else:
        title = []
        for property_value in (resource.get("properties") or {}).values():
            if property_value.get("type") == "title":
                title = property_value.get("title", [])
                break
    return "".join(part.get("plain_text", "") for part in title)


def _summarize_page(page):
    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "title": _extract_title(page),
        "archived": page.get("archived", False),
        "parent": page.get("parent"),
        "last_edited_time": page.get("last_edited_time"),
    }


def _summarize_database(database):
    return {
        "id": database.get("id"),
        "url": database.get("url"),
        "title": _extract_title(database),
        "parent": database.get("parent"),
        "properties": list((database.get("properties") or {}).keys()),
        "last_edited_time": database.get("last_edited_time"),
    }


def _has_title_property(properties):
    return any(
        isinstance(value, dict) and "title" in value
        for value in properties.values()
    )


def notion_search(inputs, context):
    def operation(token, command_inputs):
        body = {
            "query": _required_string(command_inputs, "query", allow_empty=True),
            "page_size": _page_size(command_inputs),
        }
        filter_type = command_inputs.get("filter_type")
        if filter_type is not None:
            if filter_type not in {"page", "database"}:
                raise NotionError(
                    "validation_error",
                    "'filter_type' must be 'page' or 'database'.",
                    400,
                )
            body["filter"] = {"property": "object", "value": filter_type}

        result = _request(token, "POST", "/search", body)
        results = result.get("results", [])
        return {
            "results": [
                _summarize_database(resource)
                if resource.get("object") == "database"
                else _summarize_page(resource)
                for resource in results
            ],
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
            "count": len(results),
        }

    return _run(operation, inputs, context)


def notion_get_page(inputs, context):
    def operation(token, command_inputs):
        page = _request(token, "GET", f"/pages/{_resource_id(command_inputs, 'page_id')}")
        return _summarize_page(page)

    return _run(operation, inputs, context)


def notion_create_page(inputs, context):
    def operation(token, command_inputs):
        parent_id = _required_string(command_inputs, "parent_id").strip()
        parent_type = _required_string(command_inputs, "parent_type").strip()
        if parent_type not in {"page_id", "database_id"}:
            raise NotionError(
                "validation_error",
                "'parent_type' must be 'page_id' or 'database_id'.",
                400,
            )

        title = _required_string(command_inputs, "title")
        properties = dict(_optional_object(command_inputs, "properties") or {})
        if parent_type == "database_id" and not _has_title_property(properties):
            properties["Name"] = {"title": [{"text": {"content": title}}]}
        elif parent_type == "page_id":
            properties = {"title": {"title": [{"text": {"content": title}}]}}

        page = _request(
            token,
            "POST",
            "/pages",
            {
                "parent": {
                    "type": parent_type,
                    parent_type: parent_id,
                },
                "properties": properties,
            },
        )
        return _summarize_page(page)

    return _run(operation, inputs, context)


def notion_query_database(inputs, context):
    def operation(token, command_inputs):
        body = {"page_size": _page_size(command_inputs)}
        filter_value = _optional_object(command_inputs, "filter")
        if filter_value:
            body["filter"] = filter_value
        sorts = command_inputs.get("sorts")
        if sorts is not None:
            if not isinstance(sorts, list):
                raise NotionError("validation_error", "'sorts' must be an array.", 400)
            if sorts:
                body["sorts"] = sorts

        result = _request(
            token,
            "POST",
            f"/databases/{_resource_id(command_inputs, 'database_id')}/query",
            body,
        )
        results = result.get("results", [])
        return {
            "results": [_summarize_page(resource) for resource in results],
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
            "count": len(results),
        }

    return _run(operation, inputs, context)


def notion_get_database(inputs, context):
    def operation(token, command_inputs):
        database = _request(
            token,
            "GET",
            f"/databases/{_resource_id(command_inputs, 'database_id')}",
        )
        return _summarize_database(database)

    return _run(operation, inputs, context)


def notion_create_database(inputs, context):
    def operation(token, command_inputs):
        database = _request(
            token,
            "POST",
            "/databases",
            {
                "parent": {
                    "type": "page_id",
                    "page_id": _required_string(command_inputs, "parent_page_id").strip(),
                },
                "title": [
                    {
                        "type": "text",
                        "text": {"content": _required_string(command_inputs, "title")},
                    }
                ],
                "properties": _required_object(command_inputs, "properties"),
            },
        )
        return _summarize_database(database)

    return _run(operation, inputs, context)


def notion_append_blocks(inputs, context):
    def operation(token, command_inputs):
        result = _request(
            token,
            "PATCH",
            f"/blocks/{_resource_id(command_inputs, 'block_id')}/children",
            {"children": _required_array(command_inputs, "children")},
        )
        blocks = result.get("results", [])
        return {
            "appended": len(blocks),
            "block_ids": [block.get("id") for block in blocks],
            "block_types": [block.get("type") for block in blocks],
        }

    return _run(operation, inputs, context)


def notion_archive_page(inputs, context):
    def operation(token, command_inputs):
        page = _request(
            token,
            "PATCH",
            f"/pages/{_resource_id(command_inputs, 'page_id')}",
            {"archived": True},
        )
        return _summarize_page(page)

    return _run(operation, inputs, context)
