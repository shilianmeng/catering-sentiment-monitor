"""报告表数据访问。"""
import json

from ..db.session import one, rows


def insert_report(conn, eid, rep: dict, created_by, at) -> int:
    cur = conn.execute("INSERT INTO report(event_id, title, sections, disposal_log, gen_mode, model_name, "
                       "created_by, created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                       (eid, rep["title"], json.dumps(rep["sections"], ensure_ascii=False),
                        json.dumps(rep["disposal_log"], ensure_ascii=False), rep["gen_mode"],
                        rep["model_name"], created_by, at))
    return cur.lastrowid


def get_report(conn, rid: int):
    return one(conn, "SELECT * FROM report WHERE id = %s", (rid,))


def list_reports(conn) -> list[dict]:
    return rows(conn, "SELECT r.id, r.event_id, r.title, r.gen_mode, r.model_name, r.created_by, r.created_at, "
                      "e.level FROM report r LEFT JOIN event e ON e.id = r.event_id ORDER BY r.id DESC")
