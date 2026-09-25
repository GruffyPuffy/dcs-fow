from pathlib import Path
import unittest

from fow.app import FoWService


class StubGateway:
    def public_status(self):
        return {"connected": False, "error": "offline", "snapshot": None}


class FoWServiceTest(unittest.TestCase):
    def setUp(self):
        scenario = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"
        self.service = FoWService(scenario, StubGateway())

    def test_new_game_populates_overview_without_dcs(self):
        self.assertIsNone(self.service.overview()["campaign"])
        campaign = self.service.new_game()
        overview = self.service.overview()
        self.assertEqual(campaign["phase"], "active")
        self.assertEqual(overview["campaign"]["resources"], {"red": 1000, "blue": 1000})
        self.assertTrue(overview["legal_actions"]["blue"])
        self.assertFalse(overview["persistence"]["enabled"])


if __name__ == "__main__":
    unittest.main()