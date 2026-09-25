import tempfile
from pathlib import Path
import unittest

from fow.campaign import AlgorithmicGeneral, CampaignEngine, CampaignState, Side, load_scenario
from fow.runtime import RuntimeCheckpoint


SCENARIO = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"


class RuntimeCheckpointTest(unittest.TestCase):
    def test_round_trips_campaign_and_general_random_state(self):
        engine = CampaignEngine(load_scenario(SCENARIO))
        campaign = engine.new_game()
        general = AlgorithmicGeneral(Side.BLUE, engine, 149, 500)
        general.opening_actions(campaign)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = RuntimeCheckpoint(Path(directory) / "runtime.json")
            checkpoint.save({
                "scenario_id": engine.scenario.id,
                "campaign": campaign.as_dict(),
                "generals": {"blue": general.state_dict()},
            })
            loaded = checkpoint.load()

        restored_campaign = CampaignState.from_dict(loaded["campaign"])
        restored_general = AlgorithmicGeneral(Side.BLUE, engine, 149, 500)
        restored_general.restore(loaded["generals"]["blue"])
        self.assertEqual(restored_campaign.as_dict(), campaign.as_dict())
        self.assertEqual(restored_general.state_dict(), general.state_dict())

    def test_rejects_unknown_checkpoint_version(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.json"
            path.write_text('{"version":99}')
            with self.assertRaisesRegex(ValueError, "version"):
                RuntimeCheckpoint(path).load()


if __name__ == "__main__":
    unittest.main()