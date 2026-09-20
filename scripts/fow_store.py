"""Local manual FoW ledger, retained only for the current DCS mission run."""

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
    target_alt_m REAL,
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
CREATE TABLE IF NOT EXISTS tracks (
    session INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    observed_at REAL NOT NULL,
    mission_time REAL NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS tracks_group ON tracks(session,group_name,observed_at);
CREATE TABLE IF NOT EXISTS aliases (
    session INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    alias TEXT NOT NULL,
    PRIMARY KEY(session,group_name)
);
CREATE TABLE IF NOT EXISTS roe (
    session INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    mode TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(session,group_name)
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
            if "target_alt_m" not in {row["name"] for row in db.execute("PRAGMA table_info(orders)")}:
                db.execute("ALTER TABLE orders ADD COLUMN target_alt_m REAL")
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
        # Older running missions lack an ID. Keep their time-reset behavior so
        # the viewer remains usable until the updated mission is loaded.
        mission_id = snapshot.get("mission_id", "legacy-status")
        if not isinstance(mission_id, str) or not mission_id:
            raise ValueError("Invalid DCS mission instance ID")
        with self.connection() as db:
            session = int(self.get_meta(db, "session", "1"))
            previous = float(self.get_meta(db, "mission_time", "-1"))
            if self.get_meta(db, "mission_id", "") != mission_id or \
                    (previous >= 0 and mission_time < previous - 5):
                session += 1
                for table in ("orders", "units", "tracks", "aliases", "roe"):
                    db.execute(f"DELETE FROM {table}")
            self.set_meta(db, "mission_id", mission_id)
            self.set_meta(db, "session", session)
            self.set_meta(db, "mission_time", mission_time)
            db.execute("UPDATE units SET present=0 WHERE session=?", (session,))
            current_groups = {}
            for group in snapshot.get("groups", []):
                units = group.get("units", [])
                if units:
                    lead = min(units, key=lambda unit: unit["id"])
                    current_groups[group["name"]] = lead
                    if isinstance(lead.get("lat"), (int, float)) and isinstance(lead.get("lon"), (int, float)):
                        last = db.execute("SELECT lat,lon,observed_at FROM tracks WHERE session=? AND group_name=? ORDER BY observed_at DESC LIMIT 1", (session, group["name"])).fetchone()
                        if not last or distance_m(last["lat"], last["lon"], lead["lat"], lead["lon"]) >= 15 or now - last["observed_at"] >= 60:
                            db.execute("INSERT INTO tracks VALUES(?,?,?,?,?,?)", (session, group["name"], now, mission_time, lead["lat"], lead["lon"]))
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
                WHERE session=? AND op IN ('move','air_move') AND state='accepted'
            """, (session,)).fetchall():
                unit = current_groups.get(order["group_name"])
                arrival_radius = 2000 if any(g.get("name") == order["group_name"] and g.get("category") == 0
                                             for g in snapshot.get("groups", [])) else 25
                if unit and distance_m(unit["lat"], unit["lon"], order["target_lat"], order["target_lon"]) <= arrival_radius:
                    db.execute("UPDATE orders SET state='at_target',observed_at=? WHERE id=?", (now, order["id"]))

    def create_order(self, order_id: str, op: str, group: str, lat: float | None,
                     lon: float | None, alt_m: float | None = None) -> None:
        with self.connection() as db:
            session = int(self.get_meta(db, "session", "1"))
            db.execute("""
                INSERT INTO orders(id,session,created_at,op,group_name,target_lat,target_lon,target_alt_m,state,detail)
                VALUES(?,?,?,?,?,?,?,?,'pending','Awaiting DCS reply')
            """, (order_id, session, time.time(), op, group, lat, lon, alt_m))

    def finish_order(self, order_id: str, state: str, detail: str) -> None:
        with self.connection() as db:
            row = db.execute("SELECT session,group_name,op FROM orders WHERE id=?", (order_id,)).fetchone()
            if state == "accepted" and row:
                lane = ("move", "hold") if row["op"] in ("move", "hold") else \
                    ("air_move",) if row["op"] == "air_move" else \
                    ("set_roe",) if row["op"] == "set_roe" else ()
                if lane:
                    db.execute("""
                        UPDATE orders SET state='superseded' WHERE session=? AND group_name=? AND id<>?
                        AND state IN ('accepted','at_target') AND op IN (""" + ",".join("?" for _ in lane) + ")",
                        (row["session"], row["group_name"], order_id, *lane))
            db.execute("UPDATE orders SET state=?,detail=? WHERE id=?", (state, detail, order_id))

    def rename_order_group(self, order_id: str, group_name: str) -> None:
        with self.connection() as db:
            db.execute("UPDATE orders SET group_name=? WHERE id=?", (group_name, order_id))

    def set_alias(self, group_name: str, alias: str) -> None:
        with self.connection() as db:
            session = int(self.get_meta(db, "session", "1"))
            if alias == group_name:
                db.execute("DELETE FROM aliases WHERE session=? AND group_name=?", (session, group_name))
            else:
                db.execute("""INSERT INTO aliases(session,group_name,alias) VALUES(?,?,?)
                    ON CONFLICT(session,group_name) DO UPDATE SET alias=excluded.alias""",
                    (session, group_name, alias))

    def set_roe(self, group_name: str, mode: str) -> None:
        with self.connection() as db:
            session = int(self.get_meta(db, "session", "1"))
            db.execute("""INSERT INTO roe(session,group_name,mode,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(session,group_name) DO UPDATE SET mode=excluded.mode,updated_at=excluded.updated_at""",
                (session, group_name, mode, time.time()))

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
            orders = [dict(row) for row in db.execute(
                "SELECT * FROM orders WHERE session=? ORDER BY created_at DESC LIMIT 100", (session,))]
            tracks = {}
            for row in db.execute("SELECT group_name,lat,lon,observed_at FROM tracks WHERE session=? ORDER BY observed_at DESC LIMIT 2000", (session,)):
                tracks.setdefault(row["group_name"], []).append([row["lat"], row["lon"]])
            for points in tracks.values():
                points.reverse()
            aliases = {row["group_name"]: row["alias"] for row in db.execute(
                "SELECT group_name,alias FROM aliases WHERE session=?", (session,))}
            roe = {row["group_name"]: row["mode"] for row in db.execute(
                "SELECT group_name,mode FROM roe WHERE session=?", (session,))}
            return {"session": session, "roster": counts, "orders": orders,
                    "tracks": tracks, "aliases": aliases, "roe": roe}
