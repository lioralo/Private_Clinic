import unittest
import os
import sys
from datetime import datetime, date
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'scripts'))
from export_data import json_serializer

class TestExportData(unittest.TestCase):
    def test_json_serializer(self):
        # test date
        d = date(2023, 10, 1)
        self.assertEqual(json_serializer(d), "2023-10-01")

        # test datetime
        dt = datetime(2023, 10, 1, 12, 30, 45)
        self.assertEqual(json_serializer(dt), "2023-10-01T12:30:45")

        # test Decimal
        dec = Decimal("10.5")
        self.assertEqual(json_serializer(dec), 10.5)

        # test type error
        with self.assertRaises(TypeError):
            json_serializer(object())

if __name__ == '__main__':
    unittest.main()
