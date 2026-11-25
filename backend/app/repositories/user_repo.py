"""用户表数据访问。"""
from ..db.session import one, rows


def get_user(conn, username: str):
    return one(conn, "SELECT * FROM user WHERE username = %s", (username,))
