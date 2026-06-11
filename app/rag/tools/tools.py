import json
import logging

import httpx
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def list_registry_components() -> str:
    """
    List all available components in the NachUI Design System Registry.
    Use this to see what UI components are available for you to use in your UI generation.
    Returns a JSON list of components, their slugs, and dependencies.
    """
    try:
        with httpx.Client() as client:
            res = client.get("https://api.nachui.tech/api/v1/registry")
            res.raise_for_status()
            return res.text
    except Exception as e:
        return f"Error listing registry components: {e}"


@tool
def get_component_details(slug: str) -> str:
    """
    Get the exact React/TypeScript code and details for a specific component from the registry.
    Args:
        slug: The slug of the component (e.g. 'accordion', 'button', 'badge').
    Returns the code, types, and dependencies for the component.
    """
    try:
        with httpx.Client() as client:
            res = client.get(f"https://api.nachui.tech/api/v1/registry/{slug}")
            res.raise_for_status()
            return res.text
    except Exception as e:
        return f"Error fetching details for component '{slug}': {e}"


@tool
def get_component_documentation(slug: str) -> str:
    """
    Get the markdown documentation, API references, variants, and usage examples for a component.
    Args:
        slug: The slug of the component (e.g. 'accordion', 'button', 'badge').
    Returns the documentation and API references.
    """
    try:
        with httpx.Client() as client:
            res = client.get(
                "https://api.nachui.tech/api/v1/docs", params={"slug": slug}
            )
            res.raise_for_status()
            data = res.json()
            items = data.get("data", [])
            if isinstance(items, list) and items:
                for item in items:
                    if (
                        item.get("slug") == slug
                        or item.get("slug") == f"components/{slug}"
                    ):
                        return json.dumps(item)
                return json.dumps(items[0])
            return json.dumps(data)
    except Exception as e:
        return f"Error fetching documentation for component '{slug}': {e}"


tools = [list_registry_components, get_component_details, get_component_documentation]


async def async_execute_tool(name: str, args: dict) -> str:
    if name == "list_registry_components":
        async with httpx.AsyncClient() as client:
            res = await client.get("https://api.nachui.tech/api/v1/registry")
            res.raise_for_status()
            return res.text
    elif name == "get_component_details":
        slug = args.get("slug")
        if not slug:
            return "Error: Missing slug argument."
        async with httpx.AsyncClient() as client:
            res = await client.get(f"https://api.nachui.tech/api/v1/registry/{slug}")
            res.raise_for_status()
            return res.text
    elif name == "get_component_documentation":
        slug = args.get("slug")
        if not slug:
            return "Error: Missing slug argument."
        async with httpx.AsyncClient() as client:
            res = await client.get(
                "https://api.nachui.tech/api/v1/docs", params={"slug": slug}
            )
            res.raise_for_status()
            data = res.json()
            items = data.get("data", [])
            if isinstance(items, list) and items:
                for item in items:
                    if (
                        item.get("slug") == slug
                        or item.get("slug") == f"components/{slug}"
                    ):
                        return json.dumps(item)
                return json.dumps(items[0])
            return json.dumps(data)
    else:
        return f"Unknown tool: {name}"
