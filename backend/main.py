"""
سيادة AI — Chat Engine v0.3
============================
v0.3 FIXES: كل endpoint فيه try/except + debug endpoint + robust response parsing
"""
import os, json, time, asyncio, traceback
import httpx
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# ─── Config ───
AP_BASE = os.getenv("AP_BASE_URL", "https://activepieces-production-2499.up.railway.app")
AP_EMAIL = os.getenv("AP_EMAIL", "a@siyadah-ai.com")
AP_PASSWORD = os.getenv("AP_PASSWORD", "")
AP_PROJECT_ID = os.getenv("AP_PROJECT_ID", "DPKKLCUXKInKaYKOd1nHk")

CONN_SHEETS = "054jht0IDFOFascI8rl0s"
CONN_GMAIL = "5zDkm97LpAUgp8OsbimXM"
CONN_DRIVE = "Nj9Lhmfax988Pp8P82Xba"

VER_WEBHOOK = "~0.1.1"
VER_GMAIL = "~0.11.4"
VER_SHEETS = "~0.14.6"

app = FastAPI(title="سيادة Chat Engine", version="0.3.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ─── Global exception handler (catches all 500s) ─────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"ERROR on {request.method} {request.url.path}: {exc}\n{tb}")
    return JSONResponse(status_code=500, content={
        "error": str(exc),
        "path": str(request.url.path),
        "detail": tb[-500:] if tb else "no traceback"
    })


# ─── Token Cache with TTL ─────
_token_cache: Optional[str] = None
_token_time: float = 0
TOKEN_TTL = 6 * 3600


async def get_token() -> str:
    global _token_cache, _token_time
    if _token_cache and (time.time() - _token_time) < TOKEN_TTL:
        return _token_cache
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{AP_BASE}/api/v1/authentication/sign-in",
            json={"email": AP_EMAIL, "password": AP_PASSWORD},
        )
        if resp.status_code != 200:
            raise Exception(f"Auth failed ({resp.status_code}): {resp.text[:200]}")
        _token_cache = resp.json()["token"]
        _token_time = time.time()
        return _token_cache


async def ap_request(method: str, path: str, body: dict = None) -> dict:
    global _token_cache
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60) as client:
        if method == "GET":
            resp = await client.get(f"{AP_BASE}{path}", headers=headers)
        elif method == "POST":
            resp = await client.post(f"{AP_BASE}{path}", headers=headers, json=body)
        elif method == "DELETE":
            h = {"Authorization": f"Bearer {token}"}
            resp = await client.delete(f"{AP_BASE}{path}", headers=h)
        else:
            raise ValueError(f"Unknown: {method}")

    if resp.status_code == 401:
        _token_cache = None
        token = await get_token()
        headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(timeout=60) as client:
            if method == "GET":
                resp = await client.get(f"{AP_BASE}{path}", headers=headers)
            elif method == "POST":
                resp = await client.post(f"{AP_BASE}{path}", headers=headers, json=body)

    if resp.status_code >= 400:
        raise Exception(f"AP {resp.status_code}: {resp.text[:300]}")

    try:
        return resp.json()
    except Exception:
        return {}


def extract_list(data, key="data"):
    """Safely extract list from API response — handles both {data:[...]} and [...] formats"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        val = data.get(key, [])
        return val if isinstance(val, list) else []
    return []


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {"status": "سيادة Chat Engine v0.3", "ap_base": AP_BASE, "project_id": AP_PROJECT_ID}


@app.get("/api/health")
async def check_health():
    try:
        token = await get_token()
        return {"status": "connected", "project_id": AP_PROJECT_ID, "token_ok": bool(token), "ap_base": AP_BASE}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/api/debug")
async def debug_endpoint():
    """Debug — shows raw API responses to diagnose issues"""
    results = {}
    try:
        token = await get_token()
        results["token"] = token[:20] + "..."
    except Exception as e:
        results["token_error"] = str(e)
        return results

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Test flows
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{AP_BASE}/api/v1/flows?projectId={AP_PROJECT_ID}", headers=headers)
        data = r.json()
        results["flows_status"] = r.status_code
        results["flows_type"] = str(type(data).__name__)
        if isinstance(data, dict):
            results["flows_keys"] = list(data.keys())
            items = data.get("data", [])
            results["flows_count"] = len(items) if isinstance(items, list) else "not_list"
        elif isinstance(data, list):
            results["flows_count"] = len(data)
    except Exception as e:
        results["flows_error"] = str(e)

    # Test connections
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{AP_BASE}/api/v1/app-connections?projectId={AP_PROJECT_ID}", headers=headers)
        data = r.json()
        results["conn_status"] = r.status_code
        results["conn_type"] = str(type(data).__name__)
        if isinstance(data, dict):
            results["conn_keys"] = list(data.keys())
        elif isinstance(data, list):
            results["conn_count"] = len(data)
            if data:
                results["conn_sample_keys"] = list(data[0].keys())[:6]
    except Exception as e:
        results["conn_error"] = str(e)

    # Test runs
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{AP_BASE}/api/v1/flow-runs?projectId={AP_PROJECT_ID}&limit=2", headers=headers)
        data = r.json()
        results["runs_status"] = r.status_code
        results["runs_type"] = str(type(data).__name__)
        if isinstance(data, dict):
            results["runs_keys"] = list(data.keys())
    except Exception as e:
        results["runs_error"] = str(e)

    return results


@app.get("/api/connections")
async def get_connections():
    try:
        data = await ap_request("GET", f"/api/v1/app-connections?projectId={AP_PROJECT_ID}")
        items = extract_list(data)
        connections = []
        for c in items:
            connections.append({
                "name": c.get("displayName", c.get("pieceName", "?")),
                "pieceName": c.get("pieceName", ""),
                "externalId": c.get("externalId", ""),
                "status": c.get("status", "?"),
            })
        return {"connections": connections}
    except Exception as e:
        return {"connections": [], "error": str(e)}


@app.get("/api/pieces/{piece_name}")
async def get_piece_schema(piece_name: str):
    data = await ap_request("GET", f"/api/v1/pieces/@activepieces/piece-{piece_name}")
    actions = {}
    for name, action in data.get("actions", {}).items():
        props = {}
        raw_props = action.get("props", {})
        if isinstance(raw_props, dict):
            for pname, pval in raw_props.items():
                if isinstance(pval, dict):
                    props[pname] = {"type": pval.get("type", "?"), "required": pval.get("required", False)}
        actions[name] = {"props": props}
    return {"pieceName": data.get("name"), "version": data.get("version"), "actions": actions}


@app.get("/api/flows")
async def list_flows():
    try:
        data = await ap_request("GET", f"/api/v1/flows?projectId={AP_PROJECT_ID}")
        items = extract_list(data)
        flows = []
        for f in items:
            version = f.get("version", {})
            if not isinstance(version, dict):
                version = {}
            flows.append({
                "id": f.get("id", "?"),
                "displayName": version.get("displayName", f.get("displayName", "?")),
                "status": f.get("status", "?"),
            })
        return {"flows": flows}
    except Exception as e:
        return {"flows": [], "error": str(e)}


@app.get("/api/flows/{flow_id}")
async def get_flow(flow_id: str):
    return await ap_request("GET", f"/api/v1/flows/{flow_id}")


@app.delete("/api/flows/{flow_id}")
async def delete_flow(flow_id: str):
    await ap_request("DELETE", f"/api/v1/flows/{flow_id}")
    return {"deleted": flow_id}


@app.get("/api/runs")
async def list_runs(limit: int = 5):
    try:
        data = await ap_request("GET", f"/api/v1/flow-runs?projectId={AP_PROJECT_ID}&limit={limit}")
        items = extract_list(data)
        runs = []
        for r in items:
            runs.append({
                "id": r.get("id", "?"), "flowId": r.get("flowId", "?"),
                "status": r.get("status", "?"), "duration": r.get("duration"),
                "created": r.get("created", ""),
            })
        return {"runs": runs}
    except Exception as e:
        return {"runs": [], "error": str(e)}


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    return await ap_request("GET", f"/api/v1/flow-runs/{run_id}")


@app.get("/api/templates")
async def list_templates(search: str = ""):
    data = await ap_request("GET", "/api/v1/flow-templates")
    templates = extract_list(data)
    if search:
        templates = [t for t in templates if search.lower() in json.dumps(t).lower()]
    return {"count": len(templates), "templates": templates[:20]}


# ═══════════════════════════════════════════════════════════════
# Flow Builder
# ═══════════════════════════════════════════════════════════════

class BuildFlowRequest(BaseModel):
    display_name: str
    trigger_tree: dict

class TestFlowRequest(BaseModel):
    flow_id: str
    test_data: dict

class SheetsTestRequest(BaseModel):
    spreadsheet_id: str
    test_data: dict = {"name": "تجربة سيادة", "email": "test@siyadah-ai.com", "phone": "0501234567"}


@app.post("/api/build-flow")
async def build_flow(req: BuildFlowRequest):
    steps = []
    flow = await ap_request("POST", "/api/v1/flows", {"displayName": req.display_name, "projectId": AP_PROJECT_ID})
    flow_id = flow["id"]
    steps.append({"step": "create", "flow_id": flow_id, "ok": True})

    await ap_request("POST", f"/api/v1/flows/{flow_id}", {
        "type": "IMPORT_FLOW", "request": {"displayName": req.display_name, "trigger": req.trigger_tree}
    })
    steps.append({"step": "import", "ok": True})

    await ap_request("POST", f"/api/v1/flows/{flow_id}", {"type": "LOCK_AND_PUBLISH", "request": {}})
    steps.append({"step": "publish", "ok": True})

    await ap_request("POST", f"/api/v1/flows/{flow_id}", {"type": "CHANGE_STATUS", "request": {"status": "ENABLED"}})
    steps.append({"step": "enable", "ok": True})

    return {"flow_id": flow_id, "webhook_url": f"{AP_BASE}/api/v1/webhooks/{flow_id}/sync", "status": "ENABLED", "steps": steps}


@app.post("/api/test-flow")
async def test_flow(req: TestFlowRequest):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{AP_BASE}/api/v1/webhooks/{req.flow_id}/sync",
            json=req.test_data, headers={"Content-Type": "application/json"},
        )
    try:
        webhook_result = resp.json()
    except Exception:
        webhook_result = {"raw": resp.text[:200]}

    await asyncio.sleep(2)
    runs = await ap_request("GET", f"/api/v1/flow-runs?projectId={AP_PROJECT_ID}&limit=1")
    items = extract_list(runs)
    latest = items[0] if items else {}
    return {
        "webhook_response": webhook_result,
        "latest_run": {"id": latest.get("id"), "status": latest.get("status"), "duration": latest.get("duration")}
    }


@app.post("/api/test-sheets-format")
async def test_sheets_format(req: SheetsTestRequest):
    trigger_tree = {
        "name": "trigger", "type": "PIECE_TRIGGER",
        "displayName": "Webhook — Sheets Test", "valid": True,
        "settings": {
            "pieceName": "@activepieces/piece-webhook", "pieceVersion": VER_WEBHOOK,
            "pieceType": "OFFICIAL", "packageType": "REGISTRY", "triggerName": "catch_webhook",
            "input": {"authType": "none"}, "inputUiInfo": {}
        },
        "nextAction": {
            "name": "step_1", "type": "PIECE",
            "displayName": "Sheets insert_row", "valid": True,
            "settings": {
                "pieceName": "@activepieces/piece-google-sheets", "pieceVersion": VER_SHEETS,
                "pieceType": "OFFICIAL", "packageType": "REGISTRY", "actionName": "insert_row",
                "input": {
                    "auth": f"{{{{connections['{CONN_SHEETS}']}}}}",
                    "spreadsheet_id": req.spreadsheet_id, "sheet_id": 0,
                    "first_row_headers": True,
                    "values": {"A": "{{trigger['body']['name']}}", "B": "{{trigger['body']['email']}}", "C": "{{trigger['body']['phone']}}"}
                },
                "inputUiInfo": {},
                "errorHandlingOptions": {"continueOnFailure": {"value": False}, "retryOnFailure": {"value": False}}
            },
            "nextAction": {
                "name": "step_2", "type": "PIECE",
                "displayName": "Gmail confirm", "valid": True,
                "settings": {
                    "pieceName": "@activepieces/piece-gmail", "pieceVersion": VER_GMAIL,
                    "pieceType": "OFFICIAL", "packageType": "REGISTRY", "actionName": "send_email",
                    "input": {
                        "auth": f"{{{{connections['{CONN_GMAIL}']}}}}",
                        "receiver": ["a@siyadah-ai.com"], "subject": "Sheets Test",
                        "body_type": "plain_text",
                        "body": "Name: {{trigger['body']['name']}}\nEmail: {{trigger['body']['email']}}\nPhone: {{trigger['body']['phone']}}",
                        "draft": False
                    },
                    "inputUiInfo": {},
                    "errorHandlingOptions": {"continueOnFailure": {"value": False}, "retryOnFailure": {"value": False}}
                },
                "nextAction": None
            }
        }
    }
    build = await build_flow(BuildFlowRequest(display_name="Sheets Format Test", trigger_tree=trigger_tree))
    test = await test_flow(TestFlowRequest(flow_id=build["flow_id"], test_data=req.test_data))
    return {"build": build, "test": test, "verdict": "SUCCEEDED" if test.get("latest_run", {}).get("status") == "SUCCEEDED" else "CHECK"}


# ═══════════════════════════════════════════════════════════════
# Chat — now with try/except on every command
# ═══════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    message: str

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    text = msg.message.strip()
    try:
        if "الفلوات" in text or "flows" in text.lower():
            flows = await list_flows()
            return {"type": "flows", "data": flows, "message": f"عندك {len(flows.get('flows',[]))} فلو"}

        elif "الاتصالات" in text or "connections" in text.lower():
            conns = await get_connections()
            return {"type": "connections", "data": conns, "message": f"عندك {len(conns.get('connections',[]))} اتصال"}

        elif "الحالة" in text or "status" in text.lower() or "health" in text.lower():
            h = await check_health()
            return {"type": "health", "data": h, "message": "حالة النظام"}

        elif "آخر تشغيل" in text or "runs" in text.lower():
            runs = await list_runs(limit=3)
            return {"type": "runs", "data": runs, "message": "آخر 3 تشغيلات"}

        elif "اختبار" in text and "شيت" in text:
            return {"type": "info", "message": "لاختبار Sheets:\nPOST /api/test-sheets-format\nمع spreadsheet_id"}

        else:
            return {"type": "info", "message": "مرحباً! أنا محرك سيادة.\n\nالأوامر:\n• الفلوات\n• الاتصالات\n• الحالة\n• آخر تشغيل\n• اختبار شيت"}

    except Exception as e:
        return {"type": "error", "message": f"خطأ: {str(e)}", "data": None}


# ─── Frontend ───
@app.get("/chat")
async def serve_chat():
    for d in [
        os.path.join(os.path.dirname(__file__), "static"),
        os.path.join(os.path.dirname(__file__), "..", "frontend"),
    ]:
        p = os.path.join(d, "index.html")
        if os.path.exists(p):
            return FileResponse(p)
    return JSONResponse({"error": "frontend not found", "hint": "check Dockerfile copies frontend to static/"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
