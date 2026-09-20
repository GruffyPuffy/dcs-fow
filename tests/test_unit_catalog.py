import importlib.util
from pathlib import Path
import unittest


path = Path(__file__).resolve().parents[1] / 'scripts' / 'refresh-unit-catalog.py'
spec = importlib.util.spec_from_file_location('refresh_unit_catalog', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UnitCatalogTest(unittest.TestCase):
    def test_country_lists_are_scoped_and_ignore_comments(self):
        source = '''
local units = country:get("USA").Units
cnt_unit( units.Cars.Car, "M 818")
-- cnt_unit( units.Cars.Car, "Not installed")
cnt_unit( units.Cars.Car, "M 818")
local units = country:get("RUSSIA").Units
cnt_unit( units.Cars.Car, "Ural-375")
'''
        result = module.generate(source)
        self.assertEqual([entry['label'] for entry in result['blue'].values()], ['M 818'])
        self.assertEqual([entry['label'] for entry in result['red'].values()], ['Ural-375'])


if __name__ == '__main__':
    unittest.main()
