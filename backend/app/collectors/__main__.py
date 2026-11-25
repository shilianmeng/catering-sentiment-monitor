"""命令行：python -m app.collectors [--source gz_amr] [--pages 30] [--export] [--url URL ...] [--reparse]

不带 --source 时依次采集全部 gkmlpt 官方源；--export 把库里的官方记录写回 official_seed.json。

越秀区双公示（企业全名的行政处罚决定）要显式指定，默认只翻 1 页、每个请求间隔 3 秒：
  python -m app.collectors --source yx_sgs --pages 1 --max-details 2      # 试跑
  python -m app.collectors --source yx_sgs --pages 50 --page-size 100 --since 2024-01-01
"""
import argparse
import json

from ..core.config import OFFICIAL_SOURCES
from ..db.session import connect, ensure_database, migrate
from . import pipeline, yuexiu_sgs


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m app.collectors")
    ap.add_argument("--source", choices=[s["id"] for s in OFFICIAL_SOURCES] + [yuexiu_sgs.SOURCE_ID])
    ap.add_argument("--pages", type=int, default=None, help="翻几页列表（gkmlpt 默认 10，每页约 100 篇；yx_sgs 默认 1）")
    ap.add_argument("--url", action="append", help="直接抓指定公告（可多次，gkmlpt）")
    ap.add_argument("--export", action="store_true", help="采集后导出 official_seed.json")
    ap.add_argument("--reparse", action="store_true", help="不联网，用已存快照按新规则重新解析")
    g = ap.add_argument_group("yx_sgs 越秀区双公示")
    g.add_argument("--page-size", type=int, default=20)
    g.add_argument("--since", help="只要该日期（YYYY-MM-DD）及以后的处罚决定")
    g.add_argument("--max-details", type=int, help="本次最多取几份详情")
    g.add_argument("--all-subjects", action="store_true", help="不按名称筛餐饮，全部取详情")
    g.add_argument("--guid", action="append", help="直接取指定 sGuid 的详情（可多次）")
    g.add_argument("--delay", type=float, default=yuexiu_sgs.DEFAULT_DELAY, help="请求间隔秒数")
    args = ap.parse_args(argv)

    ensure_database()
    conn = connect()
    try:
        migrate(conn)
        sources = [args.source] if args.source else [s["id"] for s in OFFICIAL_SOURCES]
        for sid in sources:
            if args.reparse:
                stats = pipeline.reparse_snapshots(conn, sid)
            elif sid == yuexiu_sgs.SOURCE_ID:
                stats = yuexiu_sgs.collect(conn, max_pages=args.pages or 1, page_size=args.page_size,
                                           since=args.since, catering_only=not args.all_subjects,
                                           max_details=args.max_details, guids=args.guid, delay=args.delay)
            else:
                stats = pipeline.collect(conn, sid, max_pages=args.pages or 10, article_urls=args.url)
            print(json.dumps(stats, ensure_ascii=False))
        if args.export:
            print(f"已导出 {pipeline.export_seed(conn)} 条到 official_seed.json")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
