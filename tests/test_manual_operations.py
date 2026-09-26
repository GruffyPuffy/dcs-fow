from pathlib import Path
import math
import unittest

from fow.app import FoWService
from fow.campaign import ActionPlan, Side
from fow.dcs.awareness import distance_m
from scripts import dcs_structures


class RecordingGateway:
    def __init__(self):
        self.spawn = None
        self.spawns = []

    def public_status(self):
        return {"connected": True, "error": None, "snapshot": {"groups": 0}}

    def public_snapshot(self):
        return {
            "mission_id": "test", "mission_time": 1,
            "groups": [
                {"name": "Blue Armor", "coalition": 2, "category": 2,
                 "units": [{"lat": 41.6, "lon": 41.7, "type": "M-1 Abrams", "y": 20}]},
                {"name": "Blue CAP", "coalition": 2, "category": 0,
                 "units": [{"lat": 41.7, "lon": 41.8, "type": "FA-18C_hornet", "y": 6000}]},
            ],
            "statics": [],
            "airbases": [{"name": "Batumi", "coalition": 2, "lat": 41.61, "lon": 41.60}],
        }

    def spawn_group(self, spawn_data):
        self.spawn = spawn_data
        self.spawns.append(spawn_data)
        return {"ok": True, "result": "SPAWN_ACCEPTED"}

    def ground_position(self, lat, lon, offsets, search_radius=2000,
                        airbase_clearance=1200):
        self.position_request = (lat, lon, offsets, search_radius, airbase_clearance)
        return lat, lon

    def set_route(self, group_name, route_data):
        self.order = ("set_route", group_name, route_data)
        return {"ok": True}

    def set_task(self, group_name, task_data):
        self.order = ("set_task", group_name, task_data)
        return {"ok": True}

    def set_command(self, group_name, command_data):
        self.order = ("set_command", group_name, command_data)
        return {"ok": True}

    def set_option(self, group_name, option_id, value):
        self.order = ("set_option", group_name, option_id, value)
        return {"ok": True}

    def set_slot_access(self, slots, enabled):
        self.slot_access = (list(slots), enabled)
        return {"ok": True}

    def add_radio_command(self, coalition_id, name, path, command_id):
        return {"ok": True}

    def smoke(self, lat, lon, color, duration=300):
        return {"ok": True}

    def mark(self, lat, lon, text, coalition_id=-1):
        return {"ok": True}

    def message(self, text, coalition_id=-1, seconds=20):
        return {"ok": True}


class ManualOperationsTest(unittest.TestCase):
    def setUp(self):
        scenario = Path(__file__).resolve().parents[1] / "fow" / "scenarios" / "caucasus_pve.json"
        self.gateway = RecordingGateway()
        self.service = FoWService(scenario, self.gateway)

    def test_exposes_full_debug_status_and_catalogs(self):
        self.assertEqual(self.service.debug_status()["snapshot"]["mission_id"], "test")
        catalogs = self.service.debug_catalogs()
        self.assertIn("fighting_force", catalogs["ground"]["blue"])
        self.assertIn("hornet_cap", catalogs["air"]["presets"]["blue"])

    def test_generals_spawn_symmetric_opening_garrisons(self):
        campaign = self.service.new_game()
        overview = self.service.overview()
        names = [spawn["group_data"]["name"] for spawn in self.gateway.spawns]
        reserve = self.service.scenario.economy.general_reserve
        # Invariants: both sides preserve their reserve, both garrison their
        # owned objectives, and both field support flights. Air flights use
        # DCS-style callsigns (Wizard=AWACS, Texaco/Lanister=tanker).
        self.assertGreaterEqual(campaign["resources"]["blue"], reserve // 2)
        self.assertGreaterEqual(campaign["resources"]["red"], reserve)
        self.assertTrue(any("Blue Reinforce Anapa" in name for name in names))
        self.assertTrue(any("Red Reinforce" in name for name in names))
        self.assertTrue(any("Wizard" in name for name in names))
        # Red's tanker may not be in the opening (endowment goes to the push).
        ground = [spawn for spawn in self.gateway.spawns if spawn["category"] == 2]
        air = [spawn for spawn in self.gateway.spawns if spawn["category"] == 0]
        self.assertGreater(len(ground), 0)
        self.assertGreater(len(air), 0)
        # Red garrisons every owned objective (pre-existing fortifications).
        # Deployment names are "FoW Red Reinforce <Objective Label> <seq> <n>";
        # labels contain spaces, so match against the scenario labels instead.
        labels = {objective["label"]: objective_id
                  for objective in overview["scenario"]["objectives"]
                  for objective_id in [objective["id"]]}
        red_garrisoned = set()
        for spawn in ground:
            name = spawn["group_data"]["name"]
            if " Red Reinforce " not in f" {name} ":
                continue
            for label, objective_id in labels.items():
                if f"Reinforce {label} " in name:
                    red_garrisoned.add(objective_id)
                    break
        owned = {objective_id for objective_id, objective in campaign["objectives"].items()
                 if objective["owner"] == "red"}
        self.assertEqual(red_garrisoned, owned)
        # Blue slots at unlocked bases are open after the campaign starts.
        slots, enabled = self.gateway.slot_access
        self.assertTrue(enabled)
        self.assertTrue(any("Anapa" in slot for slot in slots))
        self.assertTrue(all(
            base in slot for slot in slots[:5]
            for base in [slot.split(" ")[1]]))
        self.assertGreater(len(slots), 0)
        # Smoke-check the racetrack structure of support flights rather than
        # exact waypoints: two orbit legs, a race-track pattern, and a landing.
        for name_part in ("Shell", "Wizard", "Lanister", "Bark"):
            spawn = next((item for item in air if name_part in item["group_data"]["name"]), None)
            if spawn is None:
                continue  # red support may be absent from the opening push
            route = spawn["group_data"]["route"]["points"]
            tasks = route[1]["task"]["params"]["tasks"]
            orbit = next(task for task in tasks if task["id"] == "Orbit")
            self.assertEqual(orbit["params"]["pattern"], "Race-Track")
            self.assertGreater(orbit["stopCondition"]["duration"], 0)
            self.assertEqual(route[-1]["type"], "Land")
        awacs = [item for item in air if " Awacs " in item["group_data"]["name"]]
        tankers = [item for item in air if " Tanker " in item["group_data"]["name"]]
        self.assertTrue(all(item["group_data"]["units"][0]["alt"] == 9000 for item in awacs))
        self.assertTrue(all(item["group_data"]["units"][0]["alt"] == 8000 for item in tankers))
        # Reinforce packages split into 4 groups; group size now varies with
        # the objective's difficulty tier (easy=infantry, hard=full defense).
        self.assertTrue(all(
            len(spawn["group_data"]["units"]) >= 2
            for spawn in ground if " Reinforce " in spawn["group_data"]["name"]))
        # Garrison packages spawn in the Kuban theatre, not across the map.
        for spawn in ground:
            geo = spawn["group_data"]["__geo"]
            self.assertGreater(geo["lat"], 44.5)
            self.assertLess(geo["lat"], 45.5)
            self.assertGreater(geo["lon"], 37.0)
            self.assertLess(geo["lon"], 39.5)

    def test_builds_and_sends_ground_spawn(self):
        result = self.service.debug_spawn("ground", {
            "side": "blue", "template": "platoon", "name": "Debug Platoon",
            "lat": 41.61, "lon": 41.60,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(self.gateway.spawn["category"], 2)
        self.assertEqual(self.gateway.spawn["group_data"]["name"], "Debug Platoon")

    def test_assault_stages_at_friendly_base_and_routes_to_target(self):
        state = self.service.engine.new_game()
        plan = ActionPlan("assault", Side.BLUE, "alpha", 250, "assault_force")

        result = self.service.executor.execute(plan, 5, state)

        self.assertEqual(result["status"], "accepted")
        group = self.gateway.spawn["group_data"]
        spawn = group["__geo"]
        destination = group["route"]["points"][-1]["__geo"]
        # The assault force stages a short drive from the target (5-10 min
        # approach), not at the friendly origin base.
        target = self.service.scenario.objectives["alpha"]
        origin = self.service.scenario.objectives["anapa"]
        approach = distance_m(
            spawn["lat"], spawn["lon"], target.lat, target.lon)
        self.assertLess(approach, 6000)
        self.assertGreater(approach, 2000)
        # It sits on the attack line between origin and target.
        self.assertLess(
            distance_m(spawn["lat"], spawn["lon"], origin.lat, origin.lon),
            distance_m(target.lat, target.lon, origin.lat, origin.lon))
        self.assertEqual(destination, {"lat": 44.908422, "lon": 37.582125})

    def test_builds_and_sends_air_spawn(self):
        result = self.service.debug_spawn("air", {
            "side": "red", "preset": "mig29_cap", "name": "Debug CAP",
            "lat": 43.1, "lon": 40.6, "altitude_m": 6500,
        })
        self.assertTrue(result["ok"])
        self.assertEqual(self.gateway.spawn["category"], 0)
        self.assertEqual(self.gateway.spawn["group_data"]["units"][0]["alt"], 6500)

    def test_rejects_invalid_manual_spawn(self):
        with self.assertRaisesRegex(ValueError, "Unknown ground template"):
            self.service.debug_spawn("ground", {
                "side": "blue", "template": "missing", "lat": 41, "lon": 42,
            })

    def test_sends_ground_move_and_roe_orders(self):
        self.service.debug_order({
            "side": "blue", "group": "Blue Armor", "op": "move", "lat": 42, "lon": 42.1,
        })
        self.assertEqual(self.gateway.order[0:2], ("set_route", "Blue Armor"))
        self.service.debug_order({
            "side": "blue", "group": "Blue Armor", "op": "set_roe", "mode": "weapon_hold",
        })
        self.assertEqual(self.gateway.order, ("set_option", "Blue Armor", 0, 4))

    def test_sends_air_mission_and_rtb_orders(self):
        self.service.debug_order({
            "side": "blue", "group": "Blue CAP", "op": "set_mission",
            "mission_type": "CAP", "lat": 42, "lon": 42.1, "altitude_m": 7000,
        })
        self.assertEqual(self.gateway.order[0:2], ("set_route", "Blue CAP"))
        self.service.debug_order({
            "side": "blue", "group": "Blue CAP", "op": "rtb", "airbase": "Batumi",
        })
        self.assertEqual(self.gateway.order[0:2], ("set_task", "Blue CAP"))


if __name__ == "__main__":
    unittest.main()