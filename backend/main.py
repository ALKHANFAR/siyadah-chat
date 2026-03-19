"""
سيادة AI — Chat Engine Backend v0.2
====================================
القاعدة المطلقة: كل تحرك = Activepieces API أولاً
لا تكتب JSON من رأسك — لا تخمن — لا تفترض

FIXES from code review (19 مارس):
- BUG1: health() function name shadowing → renamed to check_health()
- BUG2: pieceVersion ~0.9.5 → ~0.14.6 (from Mem: actual Railway version)
- BUG3: Token cache never expires → added TTL (6 hours)
- FIX: spreadsheet_id + sheet_id (underscore) confirmed from 140 templates
"""
import os, json, time, asyncio
import httpx
from typing import Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ─── Config ───────────────────────────────────────────────────────
AP_BASE = os.getenv("AP_BASE_URL", "https://activepieces-production-2499.up.railway.app")
AP_EMAIL = os.getenv("AP_EMAIL", "a@siyadah-ai.com")
AP_PASSWORD = os.getenv("AP_PASSWORD", "")
AP_PROJECT_ID = os.getenv("AP_PROJECT_ID", "DPKKLCUXKInKaYKOd1nHk")

# Connection IDs (from GET /app-connections — verified 18 March)
CONN_SHEETS = "054jht0IDFOFascI8rl0s"
CONN_GMAIL = "5zDkm97LpAUgp8OsbimXM"
CONN_DRIVE = "Nj9Lhmfax988Pp8P82Xba"

# Piece versions (from Mem — actual installed on Railway)
VER_WEBHOOK = "~0.1.1"
VER_GMAIL = "~0.11.4"
VER_SHEETS = "~0.14.6"  # BUG2 FIX: was ~0.9.5, actual Railway version is 0.14.6

app = FastAPI(title="سيادة Chat Engine", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ─── Token Cache with TTL (BUG3 FIX) ─────────────────────────────
_token_cache: Optional[str] = None
_token_time: float = 0
TOKEN_TTL = 6 * 3600  # 6 hours (JWT valid ~7 days, refresh well before)


async def get_token() -> str:
    """Sign in → JWT Token. Auto-refreshes after TOKEN_TTL."""
    global _token_cache, _token_time
    if _token_cache and (time.time() - _token_time) < TOKEN_TTL:
        return _token_cache

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{AP_BASE}/api/v1/authentication/sign-in",
            json={"email": AP_EMAIL, "password": AP_PASSWORD},
        )
        if resp.status_code != 200:
            raise HTTPException(500, f"Auth failed: {resp.text}")
        _token_cache = resp.json()["token"]
        _token_time = time.time()
        return _token_cache


async def ap_request(method: str, path: str, body: dict = None) -> dict:
    """Generic Activepieces API request with auth. Retries once on 401."""
    global _token_cache
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60) as client:
        if method == "GET":
            resp = await client.get(f"{AP_BASE}{path}", headers=headers)
        elif method == "POST":
            resp = await client.post(f"{AP_BASE}{path}", headers=headers, json=body)
        elif method == "DELETE":
            del headers["Content-Type"]  # ERR-005
            resp = await client.delete(f"{AP_BASE}{path}", headers=headers)
        else:
            raise ValueError(f"Unknown method: {method}")

    # Auto-retry on 401 (token expired)
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
        raise HTTPException(resp.status_code, f"AP Error: {resp.text}")
    return resp.json() if resp.text else {}


# ═══════════════════════════════════════════════════════════════════
# API Endpoints
# ═══════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {"status": "سيادة Chat Engine v0.2", "ap_base": AP_BASE}


@app.get("/api/health")
async def check_health():  # BUG1 FIX: renamed from health() to avoid shadowing
    """Verify Activepieces connectivity"""
    try:
        token = await get_token()
        return {"status": "connected", "project_id": AP_PROJECT_ID, "token_ok": bool(token)}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@app.get("/api/connections")
async def get_connections():
    data = await ap_request("GET", f"/api/v1/app-connections?projectId={AP_PROJECT_ID}")
    connections = []
    for c in data.get("data", []):
        connections.append({
            "name": c.get("displayName", c.get("pieceName", "?")),
            "pieceName": c.get("pieceName"),
            "externalId": c.get("externalId"),
            "status": c.get("status"),
        })
    return {"connections": connections}


@app.get("/api/pieces/{piece_name}")
async def get_piece_schema(piece_name: str):
    data = await ap_request("GET", f"/api/v1/pieces/@activepieces/piece-{piece_name}")
    actions = {}
    for name, action in data.get("actions", {}).items():
        props = {}
        for pname, pval in action.get("props", {}).items():
            if isinstance(pval, dict):
                props[pname] = {
                    "type": pval.get("type", "?"),
                    "required": pval.get("required", False),
                    "displayName": pval.get("displayName", pname),
                }
        actions[name] = {"props": props}
    return {"pieceName": data.get("name"), "version": data.get("version"), "actions": actions}


@app.get("/api/flows")
async def list_flows():
    data = await ap_request("GET", f"/api/v1/flows?projectId={AP_PROJECT_ID}")
    flows = []
    for f in data.get("data", []):
        flows.append({
            "id": f["id"],
            "displayName": f.get("version", {}).get("displayName", "?"),
            "status": f.get("status"),
            "updatedAt": f.get("updated"),
        })
    return {"flows": flows}


@app.get("/api/flows/{flow_id}")
async def get_flow(flow_id: str):
    return await ap_request("GET", f"/api/v1/flows/{flow_id}")


@app.delete("/api/flows/{flow_id}")
async def delete_flow(flow_id: str):
    await ap_request("DELETE", f"/api/v1/flows/{flow_id}")
    return {"deleted": flow_id}


@app.get("/api/runs")
async def list_runs(limit: int = 5):
    data = await ap_request("GET", f"/api/v1/flow-runs?projectId={AP_PROJECT_ID}&limit={limit}")
    runs = []
    for r in data.get("data", []):
        runs.append({
            "id": r["id"], "flowId": r.get("flowId"), "status": r.get("status"),
            "duration": r.get("duration"), "created": r.get("created"),
        })
    return {"runs": runs}


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str):
    return await ap_request("GET", f"/api/v1/flow-runs/{run_id}")


@app.get("/api/templates")
async def list_templates(search: str = ""):
    data = await ap_request("GET", "/api/v1/flow-templates")
    templates = data if isinstance(data, list) else data.get("data", [])
    if search:
        templates = [t for t in templates if search.lower() in json.dumps(t).lower()]
    return {"count": len(templates), "templates": templates[:20]}


# ═══════════════════════════════════════════════════════════════════
# Flow Builder — Pipeline المثبت
# ═══════════════════════════════════════════════════════════════════

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
    results = {"steps": []}
    flow = await ap_request("POST", "/api/v1/flows", {"displayName": req.display_name, "projectId": AP_PROJECT_ID})
    flow_id = flow["id"]
    results["steps"].append({"step": "create", "flow_id": flow_id, "ok": True})

    await ap_request("POST", f"/api/v1/flows/{flow_id}", {
        "type": "IMPORT_FLOW", "request": {"displayName": req.display_name, "trigger": req.trigger_tree}
    })
    results["steps"].append({"step": "import", "ok": True})

    await ap_request("POST", f"/api/v1/flows/{flow_id}", {"type": "LOCK_AND_PUBLISH", "request": {}})
    results["steps"].append({"step": "publish", "ok": True})

    await ap_request("POST", f"/api/v1/flows/{flow_id}", {"type": "CHANGE_STATUS", "request": {"status": "ENABLED"}})
    results["steps"].append({"step": "enable", "ok": True})

    results["flow_id"] = flow_id
    results["webhook_url"] = f"{AP_BASE}/api/v1/webhooks/{flow_id}/sync"
    results["status"] = "ENABLED"
    return results


@app.post("/api/test-flow")
async def test_flow(req: TestFlowRequest):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{AP_BASE}/api/v1/webhooks/{req.flow_id}/sync",
            json=req.test_data, headers={"Content-Type": "application/json"},
        )
    webhook_result = resp.json() if resp.text else {}
    await asyncio.sleep(2)
    runs = await ap_request("GET", f"/api/v1/flow-runs?projectId={AP_PROJECT_ID}&limit=1")
    latest_run = runs.get("data", [{}])[0] if runs.get("data") else {}
    return {
        "webhook_response": webhook_result,
        "latest_run": {
            "id": latest_run.get("id"), "status": latest_run.get("status"),
            "duration": latest_run.get("duration"), "flowId": latest_run.get("flowId"),
        }
    }


@app.post("/api/test-sheets-format")
async def test_sheets_format(req: SheetsTestRequest):
    """إثبات format الذهبي: {"A":"...", "B":"...", "C":"..."}"""
    trigger_tree = {
        "name": "trigger", "type": "PIECE_TRIGGER",
        "displayName": "Webhook — Sheets Test", "valid": True,
        "settings": {
            "pieceName": "@activepieces/piece-webhook",
            "pieceVersion": VER_WEBHOOK, "pieceType": "OFFICIAL",
            "packageType": "REGISTRY", "triggerName": "catch_webhook",
            "input": {"authType": "none"}, "inputUiInfo": {}
        },
        "nextAction": {
            "name": "step_1", "type": "PIECE",
            "displayName": "Sheets insert_row", "valid": True,
            "settings": {
                "pieceName": "@activepieces/piece-google-sheets",
                "pieceVersion": VER_SHEETS,  # BUG2 FIX: ~0.14.6 not ~0.9.5
                "pieceType": "OFFICIAL", "packageType": "REGISTRY",
                "actionName": "insert_row",
                "input": {
                    "auth": f"{{{{connections['{CONN_SHEETS}']}}}}",
                    "spreadsheet_id": req.spreadsheet_id,
                    "sheet_id": 0,
                    "first_row_headers": True,
                    "values": {
                        "A": "{{trigger['body']['name']}}",
                        "B": "{{trigger['body']['email']}}",
                        "C": "{{trigger['body']['phone']}}",
                    }
                },
                "inputUiInfo": {},
                "errorHandlingOptions": {"continueOnFailure": {"value": False}, "retryOnFailure": {"value": False}}
            },
            "nextAction": {
                "name": "step_2", "type": "PIECE",
                "displayName": "Gmail confirm", "valid": True,
                "settings": {
                    "pieceName": "@activepieces/piece-gmail",
                    "pieceVersion": VER_GMAIL, "pieceType": "OFFICIAL",
                    "packageType": "REGISTRY", "actionName": "send_email",
                    "input": {
                        "auth": f"{{{{connections['{CONN_GMAIL}']}}}}",
                        "receiver": ["a@siyadah-ai.com"],
                        "subject": "Sheets Format Test",
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
    build_result = await build_flow(BuildFlowRequest(display_name="Sheets Format Test", trigger_tree=trigger_tree))
    test_result = await test_flow(TestFlowRequest(flow_id=build_result["flow_id"], test_data=req.test_data))
    return {
        "build": build_result, "test": test_result,
        "format_used": {"A": "string", "B": "string", "C": "string"},
        "verdict": "SUCCEEDED" if test_result.get("latest_run", {}).get("status") == "SUCCEEDED" else "CHECK"
    }


# ═══════════════════════════════════════════════════════════════════
# Chat Endpoint
# ═══════════════════════════════════════════════════════════════════

class ChatMessage(BaseModel):
    message: str

@app.post("/api/chat")
async def chat(msg: ChatMessage):
    text = msg.message.strip()

    if "الفلوات" in text or "flows" in text.lower():
        flows = await list_flows()
        return {"type": "flows", "data": flows, "message": f"عندك {len(flows['flows'])} فلو"}

    elif "الاتصالات" in text or "connections" in text.lower():
        conns = await get_connections()
        return {"type": "connections", "data": conns, "message": f"عندك {len(conns['connections'])} اتصال مفعّل"}

    elif "الحالة" in text or "status" in text.lower() or "health" in text.lower():
        h = await check_health()  # BUG1 FIX: was health() → shadowed itself
        return {"type": "health", "data": h, "message": "حالة النظام"}

    elif "آخر تشغيل" in text or "runs" in text.lower():
        runs = await list_runs(limit=3)
        return {"type": "runs", "data": runs, "message": "آخر 3 تشغيلات"}

    elif "اختبار" in text and "شيت" in text:
        return {"type": "info", "message": "لاختبار Sheets format:\nPOST /api/test-sheets-format\nمع spreadsheet_id لشيت مرئي للـ connection"}

    else:
        return {"type": "info", "message": "مرحباً! أنا محرك سيادة.\n\nالأوامر:\n• الفلوات\n• الاتصالات\n• الحالة\n• آخر تشغيل\n• اختبار شيت"}


# ─── Serve Frontend ───────────────────────────────────────────────
@app.get("/chat")
async def serve_chat():
    for d in [
        os.path.join(os.path.dirname(__file__), "static"),
        os.path.join(os.path.dirname(__file__), "..", "frontend"),
    ]:
        p = os.path.join(d, "index.html")
        if os.path.exists(p):
            return FileResponse(p)
    return {"error": "frontend not found"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
