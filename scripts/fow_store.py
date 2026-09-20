"""Persistent manual FoW order and observation ledger."""

from contextlib import contextmanager
import math
from pathlib import Path
import sqlite3
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    session INTEGER NOT NULL,
    created_at REAL NOT NULL,
    op TEXT NOT NULL,
    group_name TEXT NOT NULL,
    target_lat REAL,
    target_lon REAL,
    state TEXT NOT NULL,
    detail TEXT NOT NULL,
    observed_at REAL
);
CREATE TABLE IF NOT EXISTS units (
    session INTEGER NOT NULL,
    unit_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    group_name TEXT NOT NULL,
    coalition INTEGER NOT NULL,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    present INTEGER NOT NULL,
    PRIMARY KEY (session, unit_id)
);
"""


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius = 6371000
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2
    a += math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * earth_radius * math.asin(min(1, math.sqrt(a)))


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)
            db.execute("UPDATE orders SET state='unknown',detail='FoW server restarted before reply' WHERE state='pending'")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    @staticmethod
    def get_meta(db, key: str, default: str) -> str:
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    @staticmethod
    def set_meta(db, key: str, value: object) -> None:
        db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def record_snapshot(self, snapshot: dict) -> None:
        now = time.time()
        mission_time = float(snapshot["time"])
        with self.connection() as db:
            session = int(self.get_meta(db, "session", "1"))
            previous = float(self.get_meta(db, "mission_time", "-1"))
            if previous >= 0 and mission_time < previous - 5:
                session += 1
            self.set_meta(db, "session", session)
            self.set_meta(db, "mission_time", mission_time)
            db.execute("UPDATE units SET present=0 WHERE session=?", (session,))
            current_groups = {}
            for group in snapshot.get("groups", []):
                units = group.get("units", [])
                if units:
                    current_groups[group["name"]] = units[0]
                for unit in units:
                    db.execute("""
                        INSERT INTO units(session,unit_id,name,group_name,coalition,first_seen,last_seen,present)
                        VALUES(?,?,?,?,?,?,?,1)
                        ON CONFLICT(session,unit_id) DO UPDATE SET
                            name=excluded.name, group_name=excluded.group_name,
                            coalition=excluded.coalition, last_seen=excluded.last_seen, present=1
                    """, (session, unit["id"], unit["name"], group["name"], group["coalition"], now, now))
            for order in db.execute("""
                SELECT id,group_name,target_lat,target_lon FROM orders
                WHERE session=? AND op='move' AND state='accepted'
            """, (session,)).fetchall():
                unit = current_groups.get(order["group_name"])
                if unit and distance_m(unit["lat"], unit["lon"], order["target_lat"], order["target_lon"]) <= 25:
                    db.execute("UPDATE orders SET state='at_target',observed_at=? WHERE id=?", (now, order["id"]))

    def create_order(self, order_id: str, op: str, group: str, lat: float | None, lon: float | None) -> None:
        with self.connection() as db:
            session = int(self.get_meta(db, "session", "1"))
            db.execute("""
                INSERT INTO orders(id,session,created_at,op,group_name,target_lat,target_lon,state,detail)
                VALUES(?,?,?,?,?,?,?,'pending','Awaiting DCS reply')
            """, (order_id, session, time.time(), op, group, lat, lon))

    def finish_order(self, order_id: str, state: str, detail: str) -> None:
        with self.connection() as db:
            row = db.execute("SELECT session,group_name FROM orders WHERE id=?", (order_id,)).fetchone()
            if state == "accepted" and row:
                db.execute("""
                    UPDATE orders SET state='superseded' WHERE session=? AND group_name=? AND id<>?
                    AND state IN ('accepted','at_target')
                """, (row["session"], row["group_name"], order_id))
            db.execute("UPDATE orders SET state=?,detail=? WHERE id=?", (state, detail, order_id))

    def dashboard(self) -> dict:
        with self.connection() as db:
            session = int(self.get_meta(db, "session", "1"))
            counts = {"seen": 0, "present": 0, "missing": 0, "by_coalition": {}}
            for row in db.execute("SELECT coalition,COUNT(*) AS seen,SUM(present) AS present FROM units WHERE session=? GROUP BY coalition", (session,)):
                seen, present = row["seen"], row["present"] or 0
                counts["seen"] += seen
                counts["present"] += present
                counts["missing"] += seen - present
                counts["by_coalition"][str(row["coalition"])] = {"seen": seen, "present": present, "missing": seen - present}
            orders = [dict(row) for row in db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 100")]
            return {"session": session, "roster": counts, "orders": orders}
