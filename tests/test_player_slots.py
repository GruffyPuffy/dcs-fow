import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PlayerSlotCatalogTest(unittest.TestCase):
    def test_foothold_roster_is_blue_only_and_accounts_for_all_source_slots(self):
        roster = json.loads((ROOT / "fow" / "assets" / "foothold_pve_slots.json").read_text())
        slots = roster["fixed_wing"] + roster["helicopters"]
        self.assertEqual(roster["player_side"], "blue")
        self.assertEqual(sum(item["source_slots"] for item in slots), 107)
        self.assertEqual(len({item["aircraft"] for item in slots}), len(slots))

    def test_scenario_references_the_roster(self):
        scenario = json.loads((ROOT / "fow" / "scenarios" / "caucasus_pve.json").read_text())
        self.assertEqual(scenario["mission"]["slot_roster"], "caucasus_slots")
        self.assertEqual(scenario["mission"]["player_side"], "blue")
        objective_ids = set(scenario["objectives"])
        self.assertTrue(all(
            slot.get("unlock_objective") in objective_ids
            for slot in scenario["mission"]["client_slots"]
        ))

    def test_slot_guard_is_a_narrow_server_controlled_adapter(self):
        guard = (ROOT / "fow" / "dcs" / "slot_guard.lua").read_text()
        self.assertIn("set_slot_access", guard)
        self.assertIn("S_EVENT_BIRTH", guard)
        self.assertNotIn("capture", guard.lower())


if __name__ == "__main__":
    unittest.main()