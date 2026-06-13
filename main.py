import os
from datetime import datetime
from typing import Annotated, TypedDict

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.config import get_config
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from greennode_agentbase import GreenNodeAgentBaseApp, RequestContext, PingStatus
from greennode_agentbase.memory import MemoryClient
from greennode_agentbase.memory.models import MemoryRecordSearchRequest
from greennode_agent_bridge import AgentBaseMemoryEvents

load_dotenv()

app = GreenNodeAgentBaseApp()

# --- Memory ---
MEMORY_ID = os.environ.get("MEMORY_ID", "")
if not MEMORY_ID:
    raise ValueError("MEMORY_ID is required. Create one with /agentbase-memory.")

MEMORY_STRATEGY_ID = os.environ.get("MEMORY_STRATEGY_ID", "default")
checkpointer = AgentBaseMemoryEvents(memory_id=MEMORY_ID)
memory_client = MemoryClient()

# --- LLM ---
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
if not all([LLM_MODEL, LLM_BASE_URL, LLM_API_KEY]):
    raise ValueError("LLM_MODEL, LLM_BASE_URL, and LLM_API_KEY are required.")

llm = ChatOpenAI(model=LLM_MODEL, base_url=LLM_BASE_URL, api_key=LLM_API_KEY)

# --- Jira config ---
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "")          # e.g. https://jira.zalopay.vn
JIRA_USERNAME = os.environ.get("JIRA_USERNAME", "")          # e.g. thucnt2@vng.com.vn
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")        # Atlassian API token
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "")    # optional: e.g. PROJ
JIRA_STATUS_FILTER = os.environ.get("JIRA_STATUS_FILTER", "") # optional: e.g. "In Progress,To Do"
ACTIVE_JIRA_TASKS = os.environ.get("ACTIVE_JIRA_TASKS", "In Progress,To Do")

# --- Confluence config ---
CONFLUENCE_BASE_URL = os.environ.get("CONFLUENCE_BASE_URL", "")     # e.g. https://confluence.zalopay.vn
CONFLUENCE_SPACE_KEY = os.environ.get("CONFLUENCE_SPACE_KEY", "")   # optional: e.g. TEAM
# Falls back to Jira credentials (same Atlassian account) if not set separately
CONFLUENCE_USERNAME = os.environ.get("CONFLUENCE_USERNAME", JIRA_USERNAME)
CONFLUENCE_API_TOKEN = os.environ.get("CONFLUENCE_API_TOKEN", JIRA_API_TOKEN)

# --- Notion config ---
NOTION_API_TOKEN = os.environ.get("NOTION_API_TOKEN", "")      # Notion integration token
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")  # optional: default database ID

# --- Power Automate config ---
POWER_AUTOMATE_WEBHOOK_URL = os.environ.get("POWER_AUTOMATE_WEBHOOK_URL", "")


# --- Auth helpers ---
# jira.zalopay.vn uses SSO — Bearer PAT required, not Basic Auth
def _jira_auth() -> str:
    return f"Bearer {JIRA_API_TOKEN}"


def _confluence_auth() -> str:
    return f"Bearer {CONFLUENCE_API_TOKEN}"


# --- Long-term memory helpers ---
def _get_actor_id() -> str:
    config = get_config()
    return config["configurable"].get("actor_id", "default")


def _build_namespace(actor_id: str) -> str:
    return f"/strategies/{MEMORY_STRATEGY_ID}/actors/{actor_id}"


@tool
def remember(fact: str) -> str:
    """Store a fact in long-term memory for later retrieval.

    Args:
        fact: The fact or information to remember.
    """
    namespace = _build_namespace(_get_actor_id())
    memory_client.insert_memory_records_directly(id=MEMORY_ID, namespace=namespace, request=[fact])
    return f"Remembered: {fact}"


@tool
def recall(query: str) -> str:
    """Search long-term memory for facts relevant to a query.

    Args:
        query: Natural language search query.
    """
    namespace = _build_namespace(_get_actor_id())
    results = memory_client.search_memory_records(
        id=MEMORY_ID, namespace=namespace,
        request=MemoryRecordSearchRequest(query=query, limit=10),
    )
    if not results:
        return "No relevant memories found."
    return "\n".join(f"- {r.memory} (score: {r.score:.2f})" for r in results)


# --- Jira tools ---
@tool
def get_active_jira_tasks() -> str:
    """Fetch active Jira tasks assigned to the configured user.

    Active statuses are defined by the ACTIVE_JIRA_TASKS environment variable
    (default: "In Progress,To Do").
    """
    if not all([JIRA_BASE_URL, JIRA_USERNAME, JIRA_API_TOKEN]):
        return "Jira not configured. Set JIRA_BASE_URL, JIRA_USERNAME, JIRA_API_TOKEN in .env"

    jql = ACTIVE_JIRA_TASKS

    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            resp = client.get(
                f"{JIRA_BASE_URL}/rest/api/2/search",
                headers={"Authorization": _jira_auth(), "Accept": "application/json"},
                params={"jql": jql, "maxResults": 50, "fields": "summary,status,description,priority,updated"},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (301, 302, 303, 307, 308):
            return (
                f"Jira authentication redirect ({e.response.status_code}): {JIRA_BASE_URL} appears to be behind "
                "Azure AD SSO (Microsoft Application Proxy). A Jira Personal Access Token cannot bypass "
                "this proxy — an Azure AD OAuth2 access token is required. Please consult your IT admin."
            )
        return f"Jira API error (HTTP {e.response.status_code}): {e.response.text[:300]}"
    except httpx.RequestError as e:
        return f"Network error connecting to Jira: {str(e)}"

    issues = data.get("issues", [])
    if not issues:
        return "No Jira tasks found."

    lines = [f"Found {len(issues)} Jira task(s):"]
    for issue in issues:
        f = issue["fields"]
        lines.append(
            f"- [{issue['key']}] {f['summary']} "
            f"| Status: {f['status']['name']} "
            f"| Priority: {f['priority']['name']} "
            f"| Updated: {f.get('updated', '')[:10]}"
        )
    return "\n".join(lines)


@tool
def get_jira_task_detail(issue_key: str) -> str:
    """Get full details of a Jira task including description and subtasks.

    Args:
        issue_key: Jira issue key, e.g. 'PROJ-123'.
    """
    if not all([JIRA_BASE_URL, JIRA_API_TOKEN]):
        return "Jira not configured."

    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            resp = client.get(
                f"{JIRA_BASE_URL}/rest/api/2/issue/{issue_key}",
                headers={"Authorization": _jira_auth(), "Accept": "application/json"},
                params={"fields": "summary,status,description,priority,subtasks,comment,assignee"},
            )
            resp.raise_for_status()
            issue = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (301, 302, 303, 307, 308):
            return f"Jira authentication redirect: {JIRA_BASE_URL} requires Azure AD OAuth2. Jira PAT cannot bypass the SSO proxy."
        return f"Jira API error (HTTP {e.response.status_code}): {e.response.text[:300]}"
    except httpx.RequestError as e:
        return f"Network error connecting to Jira: {str(e)}"

    f = issue["fields"]
    desc = (f.get("description") or "No description")[:500]
    subtasks = f.get("subtasks", [])
    sub_lines = [
        f"  - [{s['key']}] {s['fields']['summary']} ({s['fields']['status']['name']})"
        for s in subtasks
    ]
    return "\n".join([
        f"[{issue['key']}] {f['summary']}",
        f"Status: {f['status']['name']} | Priority: {f['priority']['name']}",
        f"Description: {desc}",
        f"Subtasks ({len(subtasks)}):" if subtasks else "No subtasks",
        *sub_lines,
    ])


# --- Notion tools ---
def _extract_notion_title(props: dict) -> str:
    for key in ["Name", "Title", "Task", "Todo", "name", "title"]:
        if key in props and props[key].get("type") == "title":
            items = props[key].get("title", [])
            return "".join(i.get("plain_text", "") for i in items) or "(untitled)"
    return "(untitled)"


def _extract_notion_status(props: dict) -> str:
    for key in ["Status", "Done", "Checkbox", "Complete", "status", "done"]:
        if key not in props:
            continue
        prop = props[key]
        t = prop.get("type")
        if t == "status":
            return prop.get("status", {}).get("name", "Unknown")
        if t == "checkbox":
            return "Done" if prop.get("checkbox") else "Not done"
        if t == "select" and prop.get("select"):
            return prop["select"].get("name", "Unknown")
    return "Unknown"


@tool
def get_notion_todos(database_id: str = "") -> str:
    """Fetch todo items from a Notion database.

    Args:
        database_id: Notion database ID. Falls back to NOTION_DATABASE_ID env var if empty.
    """
    if not NOTION_API_TOKEN:
        return "Notion not configured. Set NOTION_API_TOKEN in .env"

    db_id = database_id or NOTION_DATABASE_ID
    if not db_id:
        return "Notion database ID not set. Set NOTION_DATABASE_ID in .env or pass it as argument."

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"https://api.notion.com/v1/databases/{db_id}/query",
                headers={
                    "Authorization": f"Bearer {NOTION_API_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json={"page_size": 100},
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        return f"Notion API error (HTTP {e.response.status_code}): {e.response.text[:300]}"
    except httpx.RequestError as e:
        return f"Network error connecting to Notion: {str(e)}"

    results = data.get("results", [])
    if not results:
        return "No todos found in the Notion database."

    lines = [f"Found {len(results)} Notion todo(s):"]
    for page in results:
        title = _extract_notion_title(page.get("properties", {}))
        status = _extract_notion_status(page.get("properties", {}))
        lines.append(f"- [ID: {page['id']}] {title} | Status: {status}")
    return "\n".join(lines)


@tool
def update_notion_todo(page_id: str, status: str) -> str:
    """Update the status of a Notion todo item.

    Args:
        page_id: The full Notion page ID.
        status: New status value (e.g. 'Done', 'In Progress', 'Not started').
    """
    if not NOTION_API_TOKEN:
        return "Notion not configured."

    is_done = status.lower() in ("done", "complete", "completed")
    payload: dict = {"properties": {}}
    if is_done:
        payload["properties"]["Done"] = {"checkbox": True}
    payload["properties"]["Status"] = {"status": {"name": status}}

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers={
                    "Authorization": f"Bearer {NOTION_API_TOKEN}",
                    "Notion-Version": "2022-06-28",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"Notion API error (HTTP {e.response.status_code}): {e.response.text[:300]}"
    except httpx.RequestError as e:
        return f"Network error connecting to Notion: {str(e)}"
    return f"Updated Notion page {page_id[:8]}... status to '{status}'"


# --- Confluence tools ---
@tool
def create_confluence_page(title: str, content: str, space_key: str = "", parent_id: str = "") -> str:
    """Create a new Confluence page.

    Args:
        title: Page title.
        content: Page body in Confluence Storage Format (XHTML-based markup).
        space_key: Confluence space key (e.g. 'TEAM'). Falls back to CONFLUENCE_SPACE_KEY env var.
        parent_id: Optional parent page ID to nest this page under.
    """
    if not all([CONFLUENCE_BASE_URL, CONFLUENCE_API_TOKEN]):
        return "Confluence not configured. Set CONFLUENCE_BASE_URL and CONFLUENCE_API_TOKEN in .env"

    effective_space = space_key or CONFLUENCE_SPACE_KEY
    if not effective_space:
        return "Confluence space key not set. Set CONFLUENCE_SPACE_KEY in .env or pass it as argument."

    body: dict = {
        "type": "page",
        "title": title,
        "space": {"key": effective_space},
        "body": {"storage": {"value": content, "representation": "storage"}},
    }
    if parent_id:
        body["ancestors"] = [{"id": parent_id}]

    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            resp = client.post(
                f"{CONFLUENCE_BASE_URL}/rest/api/content",
                headers={
                    "Authorization": _confluence_auth(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            page = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (301, 302, 303, 307, 308):
            return f"Confluence authentication redirect: {CONFLUENCE_BASE_URL} requires Azure AD OAuth2. Bearer PAT cannot bypass the SSO proxy."
        return f"Confluence API error (HTTP {e.response.status_code}): {e.response.text[:300]}"
    except httpx.RequestError as e:
        return f"Network error connecting to Confluence: {str(e)}"

    webui = page.get("_links", {}).get("webui", "")
    return f"Created Confluence page '{title}' (ID: {page['id']}) — {CONFLUENCE_BASE_URL}/wiki{webui}"


@tool
def update_confluence_page(page_id: str, title: str, content: str) -> str:
    """Update an existing Confluence page.

    Args:
        page_id: Confluence page ID.
        title: Page title (use existing title to keep it unchanged).
        content: New page body in Confluence Storage Format.
    """
    if not all([CONFLUENCE_BASE_URL, CONFLUENCE_API_TOKEN]):
        return "Confluence not configured."

    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            get_resp = client.get(
                f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}",
                headers={"Authorization": _confluence_auth(), "Accept": "application/json"},
                params={"expand": "version"},
            )
            get_resp.raise_for_status()
            current_version = get_resp.json()["version"]["number"]

            put_resp = client.put(
                f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}",
                headers={
                    "Authorization": _confluence_auth(),
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "type": "page",
                    "title": title,
                    "version": {"number": current_version + 1},
                    "body": {"storage": {"value": content, "representation": "storage"}},
                },
            )
            put_resp.raise_for_status()
            page = put_resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (301, 302, 303, 307, 308):
            return f"Confluence authentication redirect: {CONFLUENCE_BASE_URL} requires Azure AD OAuth2. Bearer PAT cannot bypass the SSO proxy."
        return f"Confluence API error (HTTP {e.response.status_code}): {e.response.text[:300]}"
    except httpx.RequestError as e:
        return f"Network error connecting to Confluence: {str(e)}"

    webui = page.get("_links", {}).get("webui", "")
    return f"Updated Confluence page '{title}' (v{current_version + 1}) — {CONFLUENCE_BASE_URL}/wiki{webui}"


# --- Notification tool ---
@tool
def notify_for_review(message: str) -> str:
    """Send a review request or notification via Power Automate webhook.

    Use when a task is ambiguous, needs clarification, or requires human review before proceeding.

    Args:
        message: The message, question, or context to send for review.
    """
    if not POWER_AUTOMATE_WEBHOOK_URL:
        return (
            f"[Review needed — webhook not configured]\n{message}\n\n"
            "Set POWER_AUTOMATE_WEBHOOK_URL in .env to enable webhook notifications."
        )

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                POWER_AUTOMATE_WEBHOOK_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "message": message,
                    "agent": "agent007",
                    "timestamp": datetime.now().isoformat(),
                },
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        return f"Webhook error (HTTP {e.response.status_code}): {e.response.text[:200]}"
    except httpx.RequestError as e:
        return f"Network error sending webhook: {str(e)}"
    return f"Review request sent: {message}"


# --- LangGraph setup ---
class State(TypedDict):
    messages: Annotated[list, add_messages]


all_tools = [
    get_active_jira_tasks,
    get_jira_task_detail,
    get_notion_todos,
    update_notion_todo,
    create_confluence_page,
    update_confluence_page,
    notify_for_review,
    remember,
    recall,
]

llm_with_tools = llm.bind_tools(all_tools)


SYSTEM_PROMPT = SystemMessage(content=(
    "You are agent007, a work management assistant for a software engineer. "
    "Always format your responses in Markdown:\n"
    "- Use **bold** for ticket IDs, key terms, and status labels\n"
    "- Use tables for listing multiple tickets or todos\n"
    "- Use bullet lists for summaries and action items\n"
    "- Use `code` for technical values (IDs, keys, commands)\n"
    "- Use headings (##) to separate sections when the response covers multiple topics\n"
    "Keep responses concise and actionable."
))


def chatbot(state: State) -> dict:
    return {"messages": [llm_with_tools.invoke([SYSTEM_PROMPT] + state["messages"])]}


graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", chatbot)
graph_builder.add_node("tools", ToolNode(all_tools, handle_tool_errors=lambda e: f"Tool error ({type(e).__name__}): {str(e)}"))
graph_builder.add_edge(START, "chatbot")
graph_builder.add_conditional_edges("chatbot", tools_condition)
graph_builder.add_edge("tools", "chatbot")
graph = graph_builder.compile(checkpointer=checkpointer)


@app.entrypoint
def handler(payload: dict, context: RequestContext) -> dict:
    """Work management agent entrypoint.

    Fetches Jira tasks and Notion todos, reports status, continues incomplete work,
    and escalates ambiguous tasks for review.
    """
    if not context.user_id or not context.session_id:
        return {
            "status": "error",
            "error": "Missing required headers: X-GreenNode-AgentBase-User-Id and X-GreenNode-AgentBase-Session-Id",
        }

    message = payload.get(
        "message",
        "Good morning! Please fetch my Jira tasks and Notion todos, report the status, "
        "continue any incomplete work, and flag anything that needs my review.",
    )
    config = {
        "configurable": {
            "thread_id": context.session_id,
            "actor_id": context.user_id,
        }
    }

    result = graph.invoke({"messages": [("user", message)]}, config)
    ai_message = result["messages"][-1]

    return {
        "status": "success",
        "response": ai_message.content,
        "timestamp": datetime.now().isoformat(),
    }


@app.ping
def health_check() -> PingStatus:
    return PingStatus.HEALTHY


# --- Web UI ---
async def me_endpoint(request: Request) -> JSONResponse:
    return JSONResponse({"user_id": os.environ.get("UI_USER_ID", "default")})

app.add_route("/me", me_endpoint, methods=["GET"])

if os.path.exists("frontend/dist"):
    app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(port=port, host="0.0.0.0")
