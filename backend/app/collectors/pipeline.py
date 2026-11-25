"""采集流水线：列表 → 筛选 → 抓正文（重试）→ 快照 → 逐案解析 → 去重入库 → 关联品牌/门店。

去重分两层：
- record_key   = sha256(来源 + 原文链接 + 案件序号)，同一起案件只有一条；
- content_hash = sha256(案件标题 + 正文)，键相同但正文变了 = 官方改过稿，revision + 1 并换成新正文。
单篇抓取失败只记进 errors，不影响其它公告。
"""
import json
import os
from datetime import datetime

from ..core.config import OFFICIAL_SEED_FILE, OFFICIAL_SOURCES
from ..db.session import one, rows
from . import gkmlpt, http, snapshot, yuexiu_sgs

_RECORD_COLS = (
    "record_key", "content_hash", "source_id", "source_name", "source_category", "official_url",
    "article_title", "doc_no", "case_no", "case_title", "subject", "enforcement_dept", "region",
    "published_at", "decided_at", "violation", "legal_basis", "regulation_text", "investigation_status",
    "handling_result", "fine_amount", "is_catering", "snapshot_sha256", "parser_version", "fetched_at",
)


def source_by_id(source_id: str) -> dict:
    for s in OFFICIAL_SOURCES:
        if s["id"] == source_id:
            return s
    raise KeyError(f"未知采集源：{source_id}")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build_record(source: dict, article: dict, case: dict, snapshot_sha: str | None) -> dict:
    return {
        "record_key": gkmlpt.record_key(source["id"], article["url"], case["case_no"]),
        "content_hash": gkmlpt.content_hash(case),
        "source_id": source["id"], "source_name": article.get("publisher") or source["name"],
        "source_category": "官方通报", "official_url": article["url"],
        "article_title": article.get("title"), "doc_no": article.get("doc_no"),
        "case_no": case["case_no"], "case_title": case["case_title"], "subject": case["subject"],
        "enforcement_dept": case.get("enforcement_dept"), "region": source.get("region"),
        "published_at": article.get("published_at"), "decided_at": case.get("decided_at"),
        "violation": case["violation"], "legal_basis": case.get("legal_basis") or [],
        "regulation_text": case.get("regulation_text"),
        "investigation_status": case["investigation_status"],
        "handling_result": case["handling_result"], "fine_amount": case.get("fine_amount"),
        "is_catering": 1 if case.get("is_catering") else 0,
        "snapshot_sha256": snapshot_sha, "parser_version": gkmlpt.PARSER_VERSION, "fetched_at": _now(),
    }


def upsert_record(conn, rec: dict, reparse: bool = False) -> str:
    """返回 inserted / revised / unchanged / reparsed。

    reparse=True：原文没变、只是解析规则升级了，刷新解析出来的字段，不算官方改稿。
    """
    old = conn.execute("SELECT id, content_hash, parser_version FROM official_record WHERE record_key = %s",
                       (rec["record_key"],)).fetchone()
    if old is not None and (rec.get("parser_version") or 0) > (old["parser_version"] or 0):
        reparse = reparse or old["content_hash"] == rec["content_hash"]   # 原文没变、规则更新了：刷新解析字段
    values = [json.dumps(rec[c], ensure_ascii=False) if c == "legal_basis" else rec[c] for c in _RECORD_COLS]
    if old is None:
        conn.execute(
            f"INSERT INTO official_record({', '.join(_RECORD_COLS)}) VALUES({', '.join(['%s'] * len(_RECORD_COLS))})",
            values)
        return "inserted"
    same = old["content_hash"] == rec["content_hash"]
    if same and not reparse:
        # 案件没变，但这篇公告别的案件可能改了稿、网页字节换了：证据指向最新一次抓到的快照，
        # 这样一篇公告的所有记录始终引用同一份「当前版本」，重新解析时不会挑到旧稿
        if rec["snapshot_sha256"]:
            conn.execute("UPDATE official_record SET snapshot_sha256 = %s WHERE id = %s",
                         (rec["snapshot_sha256"], old["id"]))
        return "unchanged"
    sets = ", ".join(f"{c} = %s" for c in _RECORD_COLS if c not in ("record_key", "fetched_at"))
    # 重新解析时原网页没变，正文 hash 变了也只是解析规则变了，不算官方改稿
    bump = "" if (same or reparse) else ", revision = revision + 1"
    conn.execute(f"UPDATE official_record SET {sets}{bump} WHERE id = %s",
                 [v for c, v in zip(_RECORD_COLS, values) if c not in ("record_key", "fetched_at")] + [old["id"]])
    return "reparsed" if (same or reparse) else "revised"


def collect(conn, source_id: str, *, max_pages: int = 10, fetch=None, snapshot_root=None,
            article_urls: list[str] | None = None) -> dict:
    """采集一个源。article_urls 给定时跳过列表，直接抓这几篇（补抓、复现用）。"""
    source = source_by_id(source_id)
    fetch = fetch or http.fetch
    stats = {"source_id": source_id, "source_name": source["name"], "pages": 0, "listed": 0,
             "candidates": 0, "articles": 0, "cases": 0, "catering": 0,
             "inserted": 0, "revised": 0, "unchanged": 0, "reparsed": 0, "errors": []}

    if article_urls:
        listed = [{"title": "", "url": u, "published_at": None, "doc_no": None} for u in article_urls]
    else:
        listed = []
        for page in range(1, max_pages + 1):
            url = gkmlpt.list_url(source, page)
            try:
                resp = fetch(url)
                items = gkmlpt.parse_list(resp.body)
            except (http.FetchError, ValueError) as e:
                stats["errors"].append({"url": url, "error": str(e)})
                break
            stats["pages"] += 1
            if not items:
                break
            listed += items
        stats["listed"] = len(listed)
        listed = [a for a in listed if gkmlpt.is_candidate(a["title"])]
    stats["candidates"] = len(listed)

    seen = set()
    for item in listed:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        try:
            resp = fetch(item["url"])
        except http.FetchError as e:
            stats["errors"].append({"url": item["url"], "error": str(e)})
            continue
        sha = snapshot.save(conn, item["url"], source_id, resp.body, resp.status, snapshot_root)
        article = gkmlpt.parse_article(resp.body, item["url"], source, item)
        stats["articles"] += 1
        for case in article["cases"]:
            stats["cases"] += 1
            stats["catering"] += 1 if case["is_catering"] else 0
            stats[upsert_record(conn, build_record(source, article, case, sha))] += 1
    stats["linked"] = link_records(conn)
    conn.commit()
    return stats


def _latest_snapshot(snaps: list[dict], cited: set[str]) -> dict:
    """一篇公告最近一次抓到的快照：按采集时间，同秒时优先有记录引用的，再按 sha 定序，结果确定。
    只给库里还没有记录的案件用；已有记录的案件各自用自己引用的那份。"""
    return max(snaps, key=lambda s: (s["fetched_at"] or "", s["sha256"] in cited, s["sha256"]))


def reparse_snapshots(conn, source_id: str | None = None, snapshot_root=None) -> dict:
    """解析规则升级后，用已存的网页快照重新解析入库，不再访问官网。

    每条已有记录只用它自己引用的那份快照重新解析：那份就是它当前版本的原文。同一篇公告的各案可能引用不同快照
    （旧版只给改了稿的案件换引用），而不同案件改过几次稿、快照采集先后都说明不了另一案的版本，
    按「整篇选一份」不管怎么排都可能把某一案刷回旧稿。引用的快照文件缺失就不动这条，宁可不刷也不回退。
    库里还没有的案件，用这篇公告最近一次抓到的快照。
    """
    stats = {"snapshots": 0, "missing": 0, "cases": 0, "inserted": 0, "revised": 0,
             "unchanged": 0, "reparsed": 0}
    sql, params = "SELECT sha256, url, source_id, fetched_at FROM source_snapshot", ()
    if source_id:
        sql, params = sql + " WHERE source_id = %s", (source_id,)
    by_url: dict[str, list[dict]] = {}
    for snap in rows(conn, sql, params):
        by_url.setdefault(snap["url"], []).append(snap)

    for url, snaps in by_url.items():
        src = snaps[0]["source_id"]
        if src == yuexiu_sgs.SOURCE_ID:
            # 一份决定书一个详情接口、一条记录：有记录就用它引用的快照，没有就用最近一次抓到的
            cited = one(conn, "SELECT snapshot_sha256 FROM official_record WHERE official_url = %s "
                              "AND source_id = %s", (url, src))
            sha = (cited or {}).get("snapshot_sha256") or _latest_snapshot(snaps, set())["sha256"]
            res = yuexiu_sgs.reparse_one(conn, url, sha, snapshot_root)
            stats["missing" if res is None else "snapshots"] += 1
            if res is not None:
                stats["cases"] += 1
                stats[res] += 1
            continue
        source = source_by_id(src)
        existing = rows(conn, "SELECT record_key, case_no, snapshot_sha256 FROM official_record "
                              "WHERE official_url = %s AND source_id = %s", (url, src))
        # 已有但没有快照引用的记录（如外部导入）：不知道它对应哪一版原文，不能拿任何快照覆盖，原样保留
        known = {r["record_key"] for r in existing}
        cited = {r["record_key"]: (r["case_no"], r["snapshot_sha256"]) for r in existing if r["snapshot_sha256"]}
        parsed: dict[str, dict | None] = {}

        def article(sha):
            if sha not in parsed:
                body = snapshot.load(sha, snapshot_root)
                parsed[sha] = None if body is None else gkmlpt.parse_article(body, url, source)
                stats["missing" if body is None else "snapshots"] += 1
            return parsed[sha]

        def save(art, case, sha):
            stats["cases"] += 1
            stats[upsert_record(conn, build_record(source, art, case, sha), reparse=True)] += 1

        for key, (case_no, sha) in cited.items():
            art = article(sha)
            case = next((c for c in art["cases"] if c["case_no"] == case_no), None) if art else None
            if case is not None:
                save(art, case, sha)
        latest = _latest_snapshot(snaps, {sha for _, sha in cited.values()})
        art = article(latest["sha256"])
        for case in (art["cases"] if art else []):
            if gkmlpt.record_key(src, url, case["case_no"]) not in known:
                save(art, case, latest["sha256"])
    link_records(conn)
    conn.commit()
    return stats


def _norm_subject(s: str | None) -> str:
    return "".join((s or "").split()).replace("(", "（").replace(")", "）")


def _match_store(stores: list[dict], subject: str | None, text: str, topic_id: int | None) -> dict | None:
    """先按营业执照主体精确对（加盟店的处罚往往只写加盟商公司名，正文里没有品牌词），
    再在已认定的品牌下按门店名/别名在正文里找。"""
    def named(s):
        return any(a and a in text for a in [s["name"], *(s["aliases"] or [])])

    def unique(cands):
        """唯一才算数；多家候选就看正文点名了哪家，还分不出来宁可留空，不挂错。"""
        if len(cands) == 1:
            return cands[0]
        hit = [s for s in cands if named(s)]
        if not hit:
            # 正文常只写区别部分（「南店」），去掉候选门店名的公共前缀（品牌、「·」）再找
            names = [s["name"] or "" for s in cands]
            k = len(os.path.commonprefix(names))
            hit = [s for s, n in zip(cands, names) if len(n[k:].strip("·・ -")) >= 2 and n[k:].strip("·・ -") in text]
        return hit[0] if len(hit) == 1 else None

    subj = _norm_subject(subject)
    if subj:
        by_subject = [s for s in stores if (topic_id is None or s["topic_id"] == topic_id)
                      and _norm_subject(s["license_subject"]) == subj]
        if by_subject:
            return unique(by_subject)            # 同一主体开了几家店：分不清就留空，不退回去按名字乱挂
    if topic_id is None:
        return None
    return unique([s for s in stores if s["topic_id"] == topic_id and named(s)])


def link_records(conn) -> int:
    """把官方记录挂到品牌（topic）和门店（store）上，返回本次挂法有变化的记录数。

    - 经营主体：门店登记的 license_subject 与当事人一致，挂到这家门店和它的品牌（同主体多家店要正文点名，分不清留空）；
    - 品牌关键词：当事人/正文里出现品牌关键词挂品牌，再在该品牌下按主体、门店名/别名找门店。

    每次都按当前门店和规则对所有记录重算，不只补空缺：门店可能是后来建的，旧版规则也可能挂错过
    （例如同主体多店时直接挂了先建的那家），这些都要能纠正。重算后挂不上的店会清空，宁可留空不挂错。
    当前所有关联都是自动的（没有手工指定门店的入口）；以后加手工指定，要给记录加锁定标记，这里跳过它们。
    品牌完全认不出（品牌停用、关键词改了）时保留原来的挂法，不把整条记录从品牌下摘掉。
    """
    topics = rows(conn, "SELECT id, keywords, enabled FROM topic")
    enabled = {t["id"] for t in topics if t["enabled"]}
    stores = [s for s in rows(conn, "SELECT id, topic_id, name, aliases, license_subject FROM store")
              if s["topic_id"] in enabled]
    n = 0
    for r in rows(conn, "SELECT id, subject, case_title, violation, topic_id, store_id FROM official_record"):
        if r["topic_id"] is not None and r["topic_id"] not in enabled:
            continue                                     # 挂在停用品牌下：不动
        text = f"{r['subject'] or ''}\n{r['case_title']}\n{r['violation'] or ''}"
        store = _match_store(stores, r["subject"], text, None)
        subj = _norm_subject(r["subject"])
        subject_topics = {s["topic_id"] for s in stores if subj and _norm_subject(s["license_subject"]) == subj}
        if store is not None:
            topic_id = store["topic_id"]
        else:
            topic = next((t for t in topics if t["enabled"] and any(k and k in text for k in t["keywords"] or [])),
                         None)
            if topic is not None:
                topic_id = topic["id"]
            elif len(subject_topics) == 1:
                topic_id = next(iter(subject_topics))    # 同主体几家店分不清是哪家，但品牌是确定的
            else:
                continue

            store = _match_store(stores, r["subject"], text, topic_id)
        store_id = store["id"] if store else None
        if (topic_id, store_id) == (r["topic_id"], r["store_id"]):
            continue
        conn.execute("UPDATE official_record SET topic_id = %s, store_id = %s WHERE id = %s",
                     (topic_id, store_id, r["id"]))
        n += 1
    return n


# ---- 随仓库提交的真实记录：离线也能演示 ----

def export_seed(conn, path=OFFICIAL_SEED_FILE) -> int:
    cols = [c for c in _RECORD_COLS if c not in ("fetched_at",)]
    recs = rows(conn, f"SELECT {', '.join(cols)}, fetched_at FROM official_record ORDER BY source_id, published_at DESC, case_no")
    doc = {"_note": "真实官方处罚公告，由 app.collectors 实际抓取生成；每条都有原文链接与网页快照 sha256。"
                    "当事人信息按官方原文照录（官方已作匿名化的保留「某」）。",
           "generated_at": _now(), "records": recs}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    return len(recs)


def _register_local_snapshot(conn, r: dict) -> None:
    """本机快照目录里有这份原网页（且 hash 对得上）就登记上，详情页能显示「快照可用」。"""
    sha = r.get("snapshot_sha256")
    if not sha:
        return
    body = snapshot.load(sha)
    if body is not None:
        snapshot.save(conn, r["official_url"], r["source_id"], body)


def load_seed(conn, path=OFFICIAL_SEED_FILE) -> int:
    """灌入随仓库的真实记录（幂等：按 record_key 去重）。文件不存在返回 0。

    种子只补库里缺的记录，不覆盖已采集的数据：库里那条要是后来重新采集过（官方改稿），快照已经换了，
    旧种子写回去就把更正冲掉了。只有库里那条和种子出自同一份快照、且种子的 parser_version 更新时，
    种子才是同一原文按更新规则的解析结果，这时按「重新解析」刷新字段，不算改稿。
    """
    try:
        with open(path, encoding="utf-8") as f:
            recs = json.load(f)["records"]
    except FileNotFoundError:
        return 0
    n = 0
    for r in recs:
        rec = {c: r.get(c) for c in _RECORD_COLS}
        rec["source_category"] = rec["source_category"] or "官方通报"
        rec["legal_basis"] = rec["legal_basis"] or []
        rec["parser_version"] = rec["parser_version"] or 0
        old = conn.execute("SELECT snapshot_sha256, parser_version FROM official_record WHERE record_key = %s",
                           (rec["record_key"],)).fetchone()
        if old is None:
            upsert_record(conn, rec)
            n += 1
        elif (rec["snapshot_sha256"] and old["snapshot_sha256"] == rec["snapshot_sha256"]
              and rec["parser_version"] > (old["parser_version"] or 0)):
            # 同一份快照，种子的解析规则比库里新才刷新；同版本或更旧的种子不能把新解析冲回去
            upsert_record(conn, rec, reparse=True)
        _register_local_snapshot(conn, r)
    link_records(conn)
    return n
