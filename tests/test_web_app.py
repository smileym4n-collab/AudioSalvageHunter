import os
import re
import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from audio_salvage_hunter.web import app as web_app
    from audio_salvage_hunter.web.database import Base, get_db
    from audio_salvage_hunter.web.importers import seed_donors_from_csv, seed_search_terms_from_config
    from audio_salvage_hunter.web.models import ScanRunRecord
    from audio_salvage_hunter.web.scheduler import scheduled_scan_mode
    from audio_salvage_hunter.web.security import safe_next_path
    from audio_salvage_hunter.web.services import mark_stale_running_scans, run_scan
    from audio_salvage_hunter.web.settings import seed_settings_from_config
except ModuleNotFoundError:  # pragma: no cover
    TestClient = None


@unittest.skipIf(TestClient is None, "web dependencies are not installed")
class WebAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.sqlite3", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        TestingSession = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, expire_on_commit=False)

        def override_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        web_app.app.dependency_overrides[get_db] = override_db
        with TestingSession() as db:
            seed_settings_from_config(db)
            seed_donors_from_csv(db)
            seed_search_terms_from_config(db)

        def sync_scan(app, scan_id):
            with TestingSession() as db:
                run_scan(db, scan_id)

        self.original_start_scan = web_app.start_scan_background
        web_app.start_scan_background = sync_scan
        os.environ["AUTH_ENABLED"] = "false"
        self.client = TestClient(web_app.app)

    def tearDown(self) -> None:
        web_app.app.dependency_overrides.clear()
        web_app.start_scan_background = self.original_start_scan
        self.tmp.cleanup()

    def test_health_endpoints(self) -> None:
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").status_code, 200)

    def test_dashboard_loads(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Dashboard", response.text)

    def test_api_donor_crud(self) -> None:
        payload = {
            "manufacturer": "Test",
            "model": "Model",
            "aliases": "",
            "category": "CD player",
            "likely_valuable_components": "DAC",
            "component_type": "standalone DAC",
            "confidence_level": "uncertain",
            "desirability_score": 50,
            "maximum_worthwhile_delivered_price_gbp": 20,
            "ideal_fault_types": "tray fault",
            "risky_fault_types": "water damage",
            "salvage_difficulty": "easy",
            "package_or_removal_notes": "",
            "source_or_verification_note": "test",
            "general_comments": "",
        }
        created = self.client.post("/api/donors", json=payload)
        self.assertEqual(created.status_code, 200)
        donor_id = created.json()["id"]
        payload["desirability_score"] = 60
        self.assertEqual(self.client.put(f"/api/donors/{donor_id}", json=payload).json()["desirability_score"], 60)
        self.assertEqual(self.client.delete(f"/api/donors/{donor_id}").json()["deleted"], True)

    def test_mock_scan_endpoint_and_listing_filtering(self) -> None:
        response = self.client.post("/api/scans", json={"mode": "mock", "notifications_enabled": False})
        self.assertEqual(response.status_code, 200)
        scan_id = response.json()["id"]
        for _ in range(50):
            status = self.client.get(f"/api/scans/{scan_id}").json()
            if status["status"] in {"success", "failed", "blocked"}:
                break
        self.assertEqual(status["status"], "success")
        listings = self.client.get("/api/listings?min_score=80&sort=score").json()
        self.assertTrue(listings)

    def test_settings_can_remove_mock_data_without_removing_settings(self) -> None:
        response = self.client.post("/api/scans", json={"mode": "mock", "notifications_enabled": False})
        self.assertEqual(response.status_code, 200)
        scan_id = response.json()["id"]
        for _ in range(50):
            status = self.client.get(f"/api/scans/{scan_id}").json()
            if status["status"] in {"success", "failed", "blocked"}:
                break
        self.assertEqual(status["status"], "success")
        self.assertEqual(len(self.client.get("/api/listings?min_score=0&limit=500").json()), 17)
        settings_page = self.client.get("/settings")
        token = re.search(r'name="csrf_token" value="([^"]+)"', settings_page.text).group(1)
        cleanup = self.client.post("/settings/remove-mock-data", data={"csrf_token": token}, follow_redirects=False)
        self.assertEqual(cleanup.status_code, 303)
        self.assertEqual(len(self.client.get("/api/listings?min_score=0&limit=500").json()), 0)
        self.assertIn("minimum_alert_score", self.client.get("/api/settings").json())

    def test_missing_credentials_live_scan_fails_cleanly(self) -> None:
        os.environ.pop("EBAY_CLIENT_ID", None)
        os.environ.pop("EBAY_CLIENT_SECRET", None)
        response = self.client.post("/api/scans", json={"mode": "live", "notifications_enabled": False})
        self.assertEqual(response.status_code, 200)

    def test_stale_running_scans_are_marked_interrupted(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(ScanRunRecord.__table__.insert().values(mode="mock", status="running"))
        TestingSession = sessionmaker(bind=self.engine)
        with TestingSession() as db:
            count = mark_stale_running_scans(db)
            self.assertEqual(count, 1)
            self.assertEqual(db.query(ScanRunRecord).first().status, "interrupted")

    def test_scheduler_uses_mock_mode_without_ebay_credentials(self) -> None:
        os.environ.pop("EBAY_CLIENT_ID", None)
        os.environ.pop("EBAY_CLIENT_SECRET", None)
        self.assertEqual(scheduled_scan_mode(mock_mode=False), "mock")

    def test_scheduler_can_use_live_mode_when_credentials_exist(self) -> None:
        os.environ["EBAY_CLIENT_ID"] = "client"
        os.environ["EBAY_CLIENT_SECRET"] = "secret"
        try:
            self.assertEqual(scheduled_scan_mode(mock_mode=False), "live")
            self.assertEqual(scheduled_scan_mode(mock_mode=True), "mock")
        finally:
            os.environ.pop("EBAY_CLIENT_ID", None)
            os.environ.pop("EBAY_CLIENT_SECRET", None)


@unittest.skipIf(TestClient is None, "web dependencies are not installed")
class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.tmp.name}/test.sqlite3", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        TestingSession = sessionmaker(bind=self.engine)

        def override_db():
            db = TestingSession()
            try:
                yield db
            finally:
                db.close()

        web_app.app.dependency_overrides[get_db] = override_db
        with TestingSession() as db:
            seed_settings_from_config(db)
        os.environ["AUTH_ENABLED"] = "true"
        os.environ["AUTH_USERNAME"] = "admin"
        os.environ["AUTH_PASSWORD_HASH"] = "sha256$2bb80d537b1da3e38bd30361aa855686bde0eacd7162fef6a25fe97bf527a25b"
        self.client = TestClient(web_app.app)

    def tearDown(self) -> None:
        web_app.app.dependency_overrides.clear()
        os.environ["AUTH_ENABLED"] = "false"
        self.tmp.cleanup()

    def test_auth_redirect_and_login(self) -> None:
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        login = self.client.post("/login", data={"username": "admin", "password": "secret", "next": "/"}, follow_redirects=False)
        self.assertEqual(login.status_code, 303)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_docs_require_auth_when_enabled(self) -> None:
        response = self.client.get("/docs", follow_redirects=False)
        self.assertEqual(response.status_code, 303)

    def test_csrf_rejects_form_without_token(self) -> None:
        self.client.post("/login", data={"username": "admin", "password": "secret", "next": "/"})
        response = self.client.post("/settings", data={})
        self.assertEqual(response.status_code, 403)

    def test_next_path_is_local_only(self) -> None:
        self.assertEqual(safe_next_path("/listings"), "/listings")
        self.assertEqual(safe_next_path("https://example.com"), "/")
        self.assertEqual(safe_next_path("//example.com"), "/")


if __name__ == "__main__":
    unittest.main()
