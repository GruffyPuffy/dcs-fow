import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fow_store import Store


def snapshot(mission_time, x=0, include_unit=True):
    return {
        "time": mission_time,
        "groups": [{"name": "Blue", "coalition": 2, "units": (
            [{"id": 7, "name": "Truck", "lat": 42.0, "lon": x}] if include_unit else []
        )}],
    }


class StoreTest(unittest.TestCase):
    def test_orders_and_observed_roster_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fow.sqlite3"
            store = Store(path)
            store.record_snapshot(snapshot(10))
            store.create_order("order1", "move", "Blue", 42.0, 0.001)
            store.finish_order("order1", "accepted", "MOVE_ACCEPTED")
            store.record_snapshot(snapshot(20, x=0.001))
            self.assertEqual(store.dashboard()["orders"][0]["state"], "at_target")

            store.record_snapshot(snapshot(30, include_unit=False))
            self.assertEqual(store.dashboard()["roster"]["missing"], 1)
            self.assertEqual(Store(path).dashboard()["roster"]["missing"], 1)

            store.record_snapshot(snapshot(1))
            self.assertEqual(store.dashboard()["session"], 2)
            self.assertEqual(store.dashboard()["roster"]["missing"], 0)
            self.assertEqual(store.dashboard()["orders"][0]["session"], 1)


if __name__ == "__main__":
    unittest.main()
