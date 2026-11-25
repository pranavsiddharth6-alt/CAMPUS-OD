import unittest
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from app.database.demo import create_demo_engine, upgrade_demo_map_od
from app.schemas.application import Coordinates
from app.services.map_od import haversine_metres, verify_location


class MapODPolicyTests(unittest.TestCase):
    def test_haversine(self):
        origin = Coordinates(latitude=0, longitude=0)
        self.assertEqual(haversine_metres(origin, origin), 0)
        self.assertAlmostEqual(haversine_metres(origin, Coordinates(latitude=1, longitude=0)), 111195.08, places=2)
        self.assertAlmostEqual(haversine_metres(
            Coordinates(latitude=0, longitude=179.999), Coordinates(latitude=0, longitude=-179.999),
        ), 222.39016, places=4)

    def test_inclusive_thresholds(self):
        self.assertEqual(verify_location(249.99, 99.9, 250, 100), "PASSED")
        self.assertEqual(verify_location(250, 100, 250, 100), "PASSED")
        self.assertEqual(verify_location(250.001, 100, 250, 100), "OUTSIDE_BOUNDARY")
        self.assertEqual(verify_location(250, 100.001, 250, 100), "POOR_ACCURACY")
        self.assertEqual(verify_location(251, 101, 250, 100), "OUTSIDE_AND_POOR_ACCURACY")

    def test_sqlite_upgrade_adds_location_fields_without_rewriting_legacy_rows(self):
        with TemporaryDirectory() as directory:
            path = Path(directory)
            with closing(sqlite3.connect(path / "campus_od.sqlite3")) as legacy:
                legacy.executescript("""
                    CREATE TABLE od_applications (id TEXT PRIMARY KEY, status TEXT);
                    CREATE TABLE evidence_submissions (id TEXT PRIMARY KEY, event_day_id TEXT, file_id TEXT);
                    CREATE TABLE location_captures (id TEXT PRIMARY KEY, evidence_submission_id TEXT, latitude FLOAT);
                    INSERT INTO od_applications VALUES ('legacy-od', 'OD_FINALIZED');
                    INSERT INTO evidence_submissions VALUES ('legacy-evidence', 'legacy-day', 'legacy-file');
                    INSERT INTO location_captures VALUES ('legacy-capture', 'legacy-evidence', 11);
                """)
            engine = create_demo_engine(path)
            try:
                upgrade_demo_map_od(engine)
                upgrade_demo_map_od(engine)
                with engine.connect() as db:
                    self.assertEqual(db.exec_driver_sql(
                        "SELECT id, status, expected_venue_latitude, expected_venue_longitude FROM od_applications"
                    ).one(), ("legacy-od", "OD_FINALIZED", None, None))
                    self.assertEqual(db.exec_driver_sql(
                        "SELECT id, event_day_id, file_id, is_location_draft, map_capture_id FROM evidence_submissions"
                    ).one(), ("legacy-evidence", "legacy-day", "legacy-file", 0, None))
                    self.assertEqual(db.exec_driver_sql(
                        "SELECT id, evidence_submission_id, latitude, verification_result FROM location_captures"
                    ).one(), ("legacy-capture", "legacy-evidence", 11, None))
            finally:
                engine.dispose()
