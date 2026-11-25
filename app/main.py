"""FastAPI 应用：26 个业务接口 + SSE 推送 + 6 个页面路由。"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import agent, auth, demo, reporting, trace
from .auth import current_user, require_role
from .config import BATCHES, SOURCE_TYPES, STATIC_DIR, TERMINAL_STATUSES, batch_label
from .db import connect, current_batch, get_config, one, rows, set_config, write_lock
from .tagging import ENTITY_DICT, GENERAL_SENSITIVE_WORDS, HIGH_RISK_WORDS, NEG_WORDS, POS_WORDS

# 处置状态机：只允许相邻流转；「忽略」可从任何未结束状态进入
NEXT_STATUS = {
    "待处理": ["跟踪中", "忽略"],
    "跟踪中": ["已核实", "忽略"],
    "已核实": ["已处理", "辟谣处理", "忽略"],
}

CONFIG_KEYS = {
    "surge_threshold": (int, 1, 10000), "surge_min_count": (int, 1, 1000),
    "level_s": (int, 1, 100), "level_a": (int, 1, 100), "level_b": (int, 1, 100),
    "silence_minutes": (int, 0, 1440), "kol_alert_weight": (int, 1, 10),
    "notify_site": (bool, None, None), "notify_email": (bool, None, None), "notify_sms": (bool, None, None),
}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- SSE 广播 ----------

class Broadcaster:
    def __init__(self):
        self.queues = set()

    def subscribe(self):
        q = asyncio.Queue(maxsize=200)
        self.queues.add(q)
        return q

    def unsubscribe(self, q):
        self.queues.discard(q)

    def publish(self, event, data):
        msg = f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        for q in list(self.queues):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass


broadcaster = Broadcaster()


@asynccontextmanager
async def lifespan(app):
    demo.ensure_db()
    yield


app = FastAPI(title="香满园舆情监测与研判平台", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def db():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def get_event_or_404(conn, eid):
    ev = one(conn, "SELECT * FROM event WHERE id = %s", (eid,))
    if not ev:
        raise HTTPException(404, f"事件 {eid} 不存在")
    return ev


# ---------- 页面 ----------

def _page(name):
    return FileResponse(STATIC_DIR / f"{name}.html", headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def page_dashboard():
    return _page("dashboard")


@app.get("/login", include_in_schema=False)
def page_login():
    return _page("login")


@app.get("/workbench", include_in_schema=False)
def page_workbench():
    return _page("workbench")


@app.get("/events/{eid}", include_in_schema=False)
def page_event(eid: str):
    return _page("event")


@app.get("/events", include_in_schema=False)
def page_events_redirect():
    return RedirectResponse("/workbench")


@app.get("/reports", include_in_schema=False)
def page_reports():
    return _page("reports")


@app.get("/settings", include_in_schema=False)
def page_settings():
    return _page("settings")


# ---------- 登录 ----------

@app.post("/api/login")
def api_login(body: dict = Body(...)):
    res = auth.login(str(body.get("username", "")).strip(), str(body.get("password", "")))
    if not res:
        raise HTTPException(401, "用户名或密码错误")
    token, user = res
    return {"token": token, **user}


@app.post("/api/logout")
def api_logout(request: Request, user=Depends(current_user)):
    h = request.headers.get("authorization", "")
    auth.logout(h[7:].strip() if h.lower().startswith("bearer ") else "")
    return {"ok": True}


@app.get("/api/me")
def api_me(user=Depends(current_user)):
    return {**user, "llm_available": agent.llm_available()}


# ---------- 大盘 ----------

_WORD_VOCAB = list(dict.fromkeys(
    HIGH_RISK_WORDS + GENERAL_SENSITIVE_WORDS + NEG_WORDS + POS_WORDS
    + [a for _, (_, aliases) in ENTITY_DICT.items() for a in aliases]
    + ["鸡腿堡", "新品", "道歉", "整改", "视频", "门店"]
))


def overview_data(conn):
    contents = rows(conn, "SELECT id, batch_no, sentiment, text, ocr_text, asr_text FROM content "
                          "WHERE dup_of IS NULL ORDER BY published_at, id")
    cur = current_batch(conn)
    n = len(contents)
    senti = {"正向": 0, "中性": 0, "负向": 0}
    for c in contents:
        senti[c["sentiment"]] = senti.get(c["sentiment"], 0) + 1
    trend = []
    for b in BATCHES:
        if b["no"] > cur:
            break
        bc = [c for c in contents if c["batch_no"] == b["no"]]
        trend.append({"label": b["label"], "time": b["time"][11:], "total": len(bc),
                      "negative": sum(1 for c in bc if c["sentiment"] == "负向"),
                      "positive": sum(1 for c in bc if c["sentiment"] == "正向")})
    freq = {}
    for c in contents:
        text = " ".join(x for x in (c["text"], c["ocr_text"], c["asr_text"]) if x)
        for w in _WORD_VOCAB:
            k = text.count(w)
            if k:
                freq[w] = freq.get(w, 0) + k
    words = [{"word": w, "count": k} for w, k in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:30]]
    active = conn.execute(
        f"SELECT COUNT(*) FROM event WHERE status NOT IN ({','.join(['%s'] * len(TERMINAL_STATUSES))})",
        tuple(TERMINAL_STATUSES)).fetchone()[0]
    alert_n = conn.execute("SELECT COUNT(*) FROM alert WHERE suppressed = 0").fetchone()[0]
    unread = conn.execute("SELECT COUNT(*) FROM alert WHERE suppressed = 0 AND is_read = 0").fetchone()[0]
    filtered = conn.execute("SELECT value FROM config WHERE `key` = 'filtered_total'").fetchone()
    merged = conn.execute("SELECT COUNT(*) FROM content WHERE dup_of IS NOT NULL").fetchone()[0]
    return {
        "metrics": {
            "total": n, "negative": senti["负向"],
            "negative_rate": round(senti["负向"] * 100 / n, 1) if n else 0,
            "active_events": active, "alerts": alert_n, "unread_alerts": unread,
            "merged": merged, "filtered": json.loads(filtered["value"]) if filtered else 0,
        },
        "trend": trend, "sentiment": senti, "words": words,
        "alerts": rows(conn, "SELECT * FROM alert ORDER BY id DESC LIMIT 12"),
        "events": rows(conn, "SELECT id, title, level, intensity_score, status, manual_override "
                             "FROM event ORDER BY intensity_score DESC, id"),
        "clock": demo.clock_state(conn),
    }


@app.get("/api/overview")
def api_overview(user=Depends(current_user), conn=Depends(db)):
    return overview_data(conn)


@app.get("/api/clock")
def api_clock(user=Depends(current_user), conn=Depends(db)):
    return demo.clock_state(conn)


@app.get("/api/stream")
async def api_stream(request: Request, token: Optional[str] = None):
    if not auth.user_for_token(token or ""):
        raise HTTPException(401, "未登录")
    q = broadcaster.subscribe()

    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broadcaster.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- 内容（研判工作台） ----------

@app.get("/api/contents")
def api_contents(topic_id: Optional[int] = None, source_type: Optional[str] = None,
                 sentiment: Optional[str] = None, level: Optional[str] = None,
                 emotion: Optional[str] = None, event_id: Optional[str] = None,
                 media_type: Optional[str] = None, start: Optional[str] = None,
                 end: Optional[str] = None, keyword: Optional[str] = None,
                 include_dup: bool = False, page: int = 1, page_size: int = 12,
                 user=Depends(current_user), conn=Depends(db)):
    where, params = [], []
    if not include_dup:
        where.append("c.dup_of IS NULL")
    for col, val in (("c.topic_id", topic_id), ("c.source_type", source_type),
                     ("c.sentiment", sentiment), ("e.level", level), ("c.emotion", emotion),
                     ("c.event_id", event_id), ("c.media_type", media_type)):
        if val not in (None, ""):
            where.append(f"{col} = %s")
            params.append(val)
    if start:
        where.append("c.published_at >= %s")
        params.append(start.replace("T", " ")[:16])
    if end:
        where.append("c.published_at <= %s")
        params.append(end.replace("T", " ")[:16])
    if keyword:
        where.append("(c.text LIKE %s OR c.ocr_text LIKE %s OR c.asr_text LIKE %s OR c.author LIKE %s)")
        params += [f"%{keyword}%"] * 4
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM content c LEFT JOIN event e ON e.id = c.event_id {sql_where}"
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    page_size = max(1, min(100, page_size))
    page = max(1, page)
    items = rows(conn, f"SELECT c.*, e.level AS event_level, e.title AS event_title {base} "
                       f"ORDER BY c.published_at DESC, c.id DESC LIMIT %s OFFSET %s",
                 params + [page_size, (page - 1) * page_size])
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/contents/{cid}")
def api_content_detail(cid: str, user=Depends(current_user), conn=Depends(db)):
    c = one(conn, "SELECT c.*, e.level AS event_level, e.title AS event_title FROM content c "
                  "LEFT JOIN event e ON e.id = c.event_id WHERE c.id = %s", (cid,))
    if not c:
        raise HTTPException(404, f"内容 {cid} 不存在")
    chain, p, seen = [], c.get("parent_id"), set()
    while p and p not in seen:
        seen.add(p)
        r = one(conn, "SELECT id, author, platform, published_at, text, parent_id FROM content WHERE id = %s", (p,))
        if not r:
            break
        chain.append(r)
        p = r["parent_id"]
    c["parent_chain"] = chain
    c["merged_items"] = rows(conn, "SELECT id, author, platform, published_at, text FROM content "
                                   "WHERE dup_of = %s ORDER BY id", (cid,))
    c["interaction"] = c["reposts"] + c["comments"] + c["likes"]
    return c


# ---------- 事件 ----------

@app.get("/api/events")
def api_events(level: Optional[str] = None, status: Optional[str] = None,
               user=Depends(current_user), conn=Depends(db)):
    where, params = [], []
    if level:
        where.append("level = %s")
        params.append(level)
    if status:
        where.append("status = %s")
        params.append(status)
    sql = "SELECT * FROM event " + ("WHERE " + " AND ".join(where) if where else "") +\
          " ORDER BY intensity_score DESC, id"
    evs = rows(conn, sql, params)
    for ev in evs:
        r = conn.execute("SELECT COUNT(*) n, SUM(sentiment='负向') neg FROM content "
                         "WHERE event_id = %s AND dup_of IS NULL", (ev["id"],)).fetchone()
        ev["content_count"], ev["negative_count"] = r["n"], r["neg"] or 0
    return evs


@app.get("/api/events/{eid}")
def api_event_detail(eid: str, user=Depends(current_user), conn=Depends(db)):
    ev = get_event_or_404(conn, eid)
    r = conn.execute("SELECT COUNT(*) n, SUM(sentiment='负向') neg FROM content "
                     "WHERE event_id = %s AND dup_of IS NULL", (eid,)).fetchone()
    ev["content_count"], ev["negative_count"] = r["n"], r["neg"] or 0
    ev["merged_count"] = conn.execute("SELECT COUNT(*) FROM content WHERE event_id = %s AND dup_of IS NOT NULL",
                                      (eid,)).fetchone()[0]
    ev["clusters"] = agent.clusters_with_quotes(conn, eid)
    ev["level_adjustments"] = rows(conn, "SELECT * FROM level_adjustment WHERE event_id = %s ORDER BY id DESC", (eid,))
    ev["next_statuses"] = NEXT_STATUS.get(ev["status"], [])
    ev["drafts"] = rows(conn, "SELECT * FROM response_draft WHERE event_id = %s ORDER BY id DESC", (eid,))
    ev["alerts"] = rows(conn, "SELECT * FROM alert WHERE event_id = %s ORDER BY id DESC", (eid,))
    ev["series"] = reporting._volume_series(
        rows(conn, "SELECT batch_no, sentiment FROM content WHERE event_id = %s AND dup_of IS NULL", (eid,)),
        current_batch(conn))
    ev["llm_available"] = agent.llm_available()
    return ev


@app.get("/api/events/{eid}/timeline")
def api_timeline(eid: str, user=Depends(current_user), conn=Depends(db)):
    get_event_or_404(conn, eid)
    return trace.timeline(conn, eid)


@app.get("/api/events/{eid}/graph")
def api_graph(eid: str, user=Depends(current_user), conn=Depends(db)):
    get_event_or_404(conn, eid)
    return trace.graph(conn, eid)


@app.post("/api/events/{eid}/level")
def api_level(eid: str, body: dict = Body(...), user=Depends(require_role("analyst", "admin")),
              conn=Depends(db)):
    new_level = str(body.get("level", "")).strip()
    reason = str(body.get("reason", "")).strip()
    if new_level not in ("S", "A", "B", "C", "auto"):
        raise HTTPException(400, "等级只能是 S / A / B / C，或 auto（恢复自动评级）")
    if not reason:
        raise HTTPException(400, "人工改级必须填写理由")
    with write_lock:
        ev = get_event_or_404(conn, eid)
        t = now_str()
        if new_level == "auto":
            conn.execute("UPDATE event SET manual_override = 0, manual_level = NULL, manual_reason = %s, "
                         "manual_by = %s, manual_at = %s, level = auto_level WHERE id = %s",
                         (reason, user["display_name"], t, eid))
            recorded = ev["auto_level"]
        else:
            conn.execute("UPDATE event SET manual_override = 1, manual_level = %s, manual_reason = %s, "
                         "manual_by = %s, manual_at = %s, level = %s WHERE id = %s",
                         (new_level, reason, user["display_name"], t, new_level, eid))
            recorded = new_level
        conn.execute("INSERT INTO level_adjustment(event_id, auto_level, auto_score, new_level, reason, "
                     "operator, created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                     (eid, ev["auto_level"], ev["auto_score"],
                      recorded if new_level != "auto" else f"恢复自动({recorded})", reason,
                      user["display_name"], t))
        conn.commit()
    return get_event_or_404(conn, eid)


@app.post("/api/events/{eid}/disposal")
def api_disposal(eid: str, body: dict = Body(...), user=Depends(require_role("pr", "admin")),
                 conn=Depends(db)):
    to = str(body.get("to_status", "")).strip()
    note = str(body.get("note", "")).strip()
    with write_lock:
        ev = get_event_or_404(conn, eid)
        cur = ev["status"]
        allowed = NEXT_STATUS.get(cur, [])
        if cur in TERMINAL_STATUSES:
            raise HTTPException(400, f"事件已是「{cur}」，处置流程已结束，不能再流转")
        if to not in allowed:
            raise HTTPException(400, f"不允许从「{cur}」直接流转到「{to}」，"
                                     f"只能流转到：{'、'.join(allowed)}")
        conn.execute("UPDATE event SET status = %s WHERE id = %s", (to, eid))
        conn.execute("INSERT INTO disposal_action(event_id, from_status, to_status, operator, role, note, "
                     "created_at) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                     (eid, cur, to, user["display_name"], user["role"], note, now_str()))
        conn.commit()
    return {"status": to, "next_statuses": NEXT_STATUS.get(to, []),
            "disposals": rows(conn, "SELECT * FROM disposal_action WHERE event_id = %s ORDER BY id", (eid,))}


@app.get("/api/events/{eid}/disposals")
def api_disposals(eid: str, user=Depends(current_user), conn=Depends(db)):
    get_event_or_404(conn, eid)
    return rows(conn, "SELECT * FROM disposal_action WHERE event_id = %s ORDER BY id", (eid,))


@app.post("/api/events/{eid}/response-draft")
def api_response_draft(eid: str, user=Depends(current_user), conn=Depends(db)):
    get_event_or_404(conn, eid)
    cfg = get_config(conn)
    text, gen_mode, model = agent.generate_draft(conn, eid, cfg)
    with write_lock:
        cur = conn.execute("INSERT INTO response_draft(event_id, content, gen_mode, model_name, created_by, "
                           "created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                           (eid, text, gen_mode, model, user["display_name"], now_str()))
        conn.commit()
    return one(conn, "SELECT * FROM response_draft WHERE id = %s", (cur.lastrowid,))


@app.post("/api/events/{eid}/draft-adopt")
def api_draft_adopt(eid: str, body: dict = Body(default={}), user=Depends(require_role("pr", "admin")),
                    conn=Depends(db)):
    get_event_or_404(conn, eid)
    did = body.get("draft_id")
    d = (one(conn, "SELECT * FROM response_draft WHERE id = %s AND event_id = %s", (did, eid)) if did
         else one(conn, "SELECT * FROM response_draft WHERE event_id = %s ORDER BY id DESC LIMIT 1", (eid,)))
    if not d:
        raise HTTPException(400, "还没有话术草案，请先生成")
    with write_lock:
        conn.execute("UPDATE response_draft SET adopted = 0 WHERE event_id = %s", (eid,))
        conn.execute("UPDATE response_draft SET adopted = 1, adopted_by = %s, adopted_at = %s WHERE id = %s",
                     (user["display_name"], now_str(), d["id"]))
        conn.commit()
    return one(conn, "SELECT * FROM response_draft WHERE id = %s", (d["id"],))


# ---------- 报告 ----------

@app.post("/api/events/{eid}/report")
def api_make_report(eid: str, user=Depends(require_role("analyst", "admin")), conn=Depends(db)):
    get_event_or_404(conn, eid)
    rep = reporting.build_report(conn, eid, get_config(conn))
    with write_lock:
        cur = conn.execute("INSERT INTO report(event_id, title, sections, disposal_log, gen_mode, model_name, "
                           "created_by, created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                           (eid, rep["title"], json.dumps(rep["sections"], ensure_ascii=False),
                            json.dumps(rep["disposal_log"], ensure_ascii=False), rep["gen_mode"],
                            rep["model_name"], user["display_name"], now_str()))
        conn.commit()
    return _report(conn, cur.lastrowid)


def _report(conn, rid):
    r = one(conn, "SELECT * FROM report WHERE id = %s", (rid,))
    if not r:
        raise HTTPException(404, f"报告 {rid} 不存在")
    r["markdown"] = reporting.to_markdown(r)
    return r


@app.get("/api/reports")
def api_reports(user=Depends(current_user), conn=Depends(db)):
    return rows(conn, "SELECT r.id, r.event_id, r.title, r.gen_mode, r.model_name, r.created_by, r.created_at, "
                      "e.level FROM report r LEFT JOIN event e ON e.id = r.event_id ORDER BY r.id DESC")


@app.get("/api/reports/{rid}")
def api_report(rid: int, user=Depends(current_user), conn=Depends(db)):
    return _report(conn, rid)


@app.get("/api/reports/{rid}/export")
def api_report_export(rid: int, format: str = "md", user=Depends(current_user), conn=Depends(db)):
    r = _report(conn, rid)
    fname = f"report_{rid}_{r['event_id']}"
    if format == "md":
        return Response(r["markdown"].encode("utf-8"), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.md"'})
    if format == "pdf":
        series = reporting._volume_series(
            rows(conn, "SELECT batch_no, sentiment FROM content WHERE event_id = %s AND dup_of IS NULL",
                 (r["event_id"],)), current_batch(conn))
        try:
            data = reporting.to_pdf(r, series)
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        return Response(data, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.pdf"'})
    raise HTTPException(400, "format 只能是 md 或 pdf")


# ---------- 监测主题 ----------

def _clean_topic(body):
    name = str(body.get("name", "")).strip()
    kws = body.get("keywords", [])
    if isinstance(kws, str):
        kws = [k for k in (x.strip() for x in kws.replace("，", ",").split(",")) if k]
    kws = [str(k).strip() for k in kws if str(k).strip()]
    if not name:
        raise HTTPException(400, "主题名称不能为空")
    if not kws:
        raise HTTPException(400, "至少填写一个关键词")
    ch = body.get("channels") or {}
    channels = {s: bool(ch.get(s, True)) for s in SOURCE_TYPES}
    return name, kws, channels, 1 if body.get("enabled", True) else 0


@app.get("/api/topics")
def api_topics(user=Depends(current_user), conn=Depends(db)):
    ts = rows(conn, "SELECT * FROM topic ORDER BY id")
    for t in ts:
        t["content_count"] = conn.execute("SELECT COUNT(*) FROM content WHERE topic_id = %s AND dup_of IS NULL",
                                          (t["id"],)).fetchone()[0]
    return ts


@app.post("/api/topics")
def api_topic_create(body: dict = Body(...), user=Depends(require_role("analyst", "admin")), conn=Depends(db)):
    name, kws, channels, enabled = _clean_topic(body)
    with write_lock:
        cur = conn.execute("INSERT INTO topic(name, keywords, channels, created_by, enabled) VALUES(%s,%s,%s,%s,%s)",
                           (name, json.dumps(kws, ensure_ascii=False), json.dumps(channels, ensure_ascii=False),
                            user["username"], enabled))
        conn.commit()
    return one(conn, "SELECT * FROM topic WHERE id = %s", (cur.lastrowid,))


@app.put("/api/topics/{tid}")
def api_topic_update(tid: int, body: dict = Body(...), user=Depends(require_role("analyst", "admin")),
                     conn=Depends(db)):
    old = one(conn, "SELECT * FROM topic WHERE id = %s", (tid,))
    if not old:
        raise HTTPException(404, "主题不存在")
    merged = {**old, **body}
    name, kws, channels, enabled = _clean_topic(merged)
    with write_lock:
        conn.execute("UPDATE topic SET name = %s, keywords = %s, channels = %s, enabled = %s WHERE id = %s",
                     (name, json.dumps(kws, ensure_ascii=False), json.dumps(channels, ensure_ascii=False),
                      enabled, tid))
        conn.commit()
    return one(conn, "SELECT * FROM topic WHERE id = %s", (tid,))


@app.delete("/api/topics/{tid}")
def api_topic_delete(tid: int, user=Depends(require_role("analyst", "admin")), conn=Depends(db)):
    if not one(conn, "SELECT id FROM topic WHERE id = %s", (tid,)):
        raise HTTPException(404, "主题不存在")
    with write_lock:
        if (conn.execute("SELECT 1 FROM content WHERE topic_id = %s LIMIT 1", (tid,)).fetchone()
                or conn.execute("SELECT 1 FROM event WHERE topic_id = %s LIMIT 1", (tid,)).fetchone()):
            raise HTTPException(409, "主题已关联内容或事件，不能删除；可停用该主题")
        conn.execute("DELETE FROM topic WHERE id = %s", (tid,))
        conn.commit()
    return {"ok": True}


# ---------- 配置 ----------

@app.get("/api/config")
def api_config(user=Depends(current_user), conn=Depends(db)):
    cfg = get_config(conn)
    return {k: cfg[k] for k in CONFIG_KEYS} | {"llm_model": cfg["llm_model"],
                                              "llm_available": agent.llm_available()}


@app.put("/api/config")
def api_config_update(body: dict = Body(...), user=Depends(require_role("admin")), conn=Depends(db)):
    cfg = get_config(conn)
    changes = {}
    for k, v in body.items():
        if k not in CONFIG_KEYS:
            continue
        typ, lo, hi = CONFIG_KEYS[k]
        if typ is bool:
            changes[k] = bool(v)
        else:
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} 必须是整数")
            if not lo <= iv <= hi:
                raise HTTPException(400, f"{k} 取值范围 {lo}–{hi}")
            changes[k] = iv
    new = {**cfg, **changes}
    if not new["level_s"] > new["level_a"] > new["level_b"]:
        raise HTTPException(400, "等级分数线必须满足 S > A > B")
    with write_lock:
        for k, v in changes.items():
            set_config(conn, k, v)
        conn.commit()
    if any(k.startswith("level_") for k in changes):
        demo.recompute_all_levels()
    return api_config(user, conn)


# ---------- 预警 ----------

@app.get("/api/alerts")
def api_alerts(event_id: Optional[str] = None, user=Depends(current_user), conn=Depends(db)):
    if event_id:
        return rows(conn, "SELECT * FROM alert WHERE event_id = %s ORDER BY id DESC", (event_id,))
    return rows(conn, "SELECT * FROM alert ORDER BY id DESC")


@app.put("/api/alerts/{aid}/read")
def api_alert_read(aid: int, user=Depends(current_user), conn=Depends(db)):
    with write_lock:
        n = conn.execute("UPDATE alert SET is_read = 1 WHERE id = %s", (aid,)).rowcount
        conn.commit()
    if not n:
        raise HTTPException(404, "预警不存在")
    return {"ok": True}


# ---------- 演示控制 ----------

def _publish_results(res):
    conn = connect()
    try:
        snap = overview_data(conn)
        for r in res["results"]:
            for aid in r["alert_ids"]:
                broadcaster.publish("alert_raised", one(conn, "SELECT * FROM alert WHERE id = %s", (aid,)))
        broadcaster.publish("batch_advanced", {
            "clock": snap["clock"], "metrics": snap["metrics"],
            "new_contents": sum(r["ingested"] for r in res["results"]),
            "merged": sum(len(r["merged"]) for r in res["results"]),
            "label": res["current_label"],
        })
    finally:
        conn.close()


@app.post("/api/demo/reset")
async def api_demo_reset(user=Depends(require_role("admin"))):
    res = demo.reset()
    broadcaster.publish("reset", {"label": res["current_label"]})
    _publish_results(res)
    return res


@app.post("/api/demo/advance")
async def api_demo_advance(body: dict = Body(default={}), user=Depends(require_role("admin"))):
    res = demo.advance(body.get("batches", 1) or 1)
    if not res["results"]:
        return JSONResponse({**res, "message": f"已到最后一批（{res['current_label']}），请先重置演示"})
    _publish_results(res)
    return res
