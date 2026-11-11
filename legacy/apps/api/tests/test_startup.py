"""Startup validation and migration gate tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from sqlalchemy import text

PROJECT = Path(__file__).resolve().parents[3]
API_DIR = Path(__file__).resolve().parents[1]
ENGINE_DIR = PROJECT / "metal-doc-agent"
for path in (str(API_DIR), str(ENGINE_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from hanson_api.config import PlatformSettings  # noqa: E402
from hanson_api.db import build_engine, verify_migrations  # noqa: E402
from hanson_api.startup import startup_issues  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402


def _production_platform(root: Path) -> PlatformSettings:
    return PlatformSettings(
        data_dir=root / "platform",
        database_url="postgresql+psycopg://hanson@localhost/hanson",
        secret_key="s" * 40,
        upload_dir=root / "platform" / "uploads",
        engine_data_dir=root / "engine",
        engine_root=ENGINE_DIR,
        inline_jobs=False,
        environment="production",
        db_auto_create=False,
    )


def _production_engine(data_dir: Path) -> Settings:
    return Settings(
        project_root=ENGINE_DIR,
        data_dir=data_dir,
        ocr_backend="glm",
        extractor_backend="qwen",
        glm_ocr_base_url="http://127.0.0.1:9977/v1",
        glm_ocr_model="GLM-OCR",
        qwen_base_url="http://127.0.0.1:9991/v1",
        qwen_model="Qwen3.5-9B",
        api_key=None,
        request_timeout=120.0,
        layout_service_url="http://127.0.0.1:9978",
        extractor_prompt_style="sft_m2",
        sft_base_url="http://127.0.0.1:9991/v1",
        sft_model="adapter-v5",
    )


class StartupCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_dev_allows_mock(self) -> None:
        settings = PlatformSettings(
            data_dir=self.root,
            database_url=f"sqlite:///{(self.root / 'dev.db').as_posix()}",
            secret_key="dev",
            upload_dir=self.root / "uploads",
            engine_data_dir=self.root / "engine",
            engine_root=ENGINE_DIR,
        )
        engine = Settings(
            project_root=ENGINE_DIR,
            data_dir=self.root / "engine",
            ocr_backend="mock",
            extractor_backend="mock",
            glm_ocr_base_url=None,
            glm_ocr_model="GLM-OCR",
            qwen_base_url=None,
            qwen_model="Qwen3.5-9B",
            api_key=None,
            request_timeout=10.0,
        )
        self.assertEqual(startup_issues(settings, engine), [])

    def test_production_valid_config_passes(self) -> None:
        issues = startup_issues(
            _production_platform(self.root),
            _production_engine(self.root / "engine"),
        )
        self.assertEqual(issues, [])

    def test_production_rejects_mock_backends(self) -> None:
        engine = Settings(
            project_root=ENGINE_DIR,
            data_dir=self.root / "engine",
            ocr_backend="mock",
            extractor_backend="mock",
            glm_ocr_base_url=None,
            glm_ocr_model="GLM-OCR",
            qwen_base_url=None,
            qwen_model="Qwen3.5-9B",
            api_key=None,
            request_timeout=10.0,
        )
        issues = startup_issues(_production_platform(self.root), engine)
        self.assertTrue(any("mock OCR" in issue for issue in issues), issues)
        self.assertTrue(any("mock extractor" in issue for issue in issues), issues)

    def test_production_rejects_placeholder_secret(self) -> None:
        settings = PlatformSettings(
            data_dir=self.root,
            database_url="postgresql+psycopg://hanson@localhost/hanson",
            secret_key="change-me-in-production",
            upload_dir=self.root / "uploads",
            engine_data_dir=self.root / "engine",
            engine_root=ENGINE_DIR,
            inline_jobs=False,
            environment="production",
            db_auto_create=False,
        )
        issues = startup_issues(settings, _production_engine(self.root / "engine"))
        self.assertTrue(any("HANSON_SECRET_KEY" in issue for issue in issues), issues)

    def test_production_rejects_sqlite_and_auto_create(self) -> None:
        settings = PlatformSettings(
            data_dir=self.root,
            database_url=f"sqlite:///{(self.root / 'prod.db').as_posix()}",
            secret_key="s" * 40,
            upload_dir=self.root / "uploads",
            engine_data_dir=self.root / "engine",
            engine_root=ENGINE_DIR,
            inline_jobs=False,
            environment="production",
            db_auto_create=True,
        )
        issues = startup_issues(settings, _production_engine(self.root / "engine"))
        self.assertTrue(any("PostgreSQL" in issue for issue in issues), issues)
        self.assertTrue(any("create tables" in issue for issue in issues), issues)

    def test_production_rejects_inline_jobs(self) -> None:
        settings = PlatformSettings(
            data_dir=self.root,
            database_url="postgresql+psycopg://hanson@localhost/hanson",
            secret_key="s" * 40,
            upload_dir=self.root / "uploads",
            engine_data_dir=self.root / "engine",
            engine_root=ENGINE_DIR,
            inline_jobs=True,
            environment="production",
            db_auto_create=False,
        )
        issues = startup_issues(settings, _production_engine(self.root / "engine"))
        self.assertTrue(any("HANSON_INLINE_JOBS" in issue for issue in issues), issues)

    def test_production_requires_layout_service(self) -> None:
        engine = replace(
            _production_engine(self.root / "engine"), layout_service_url=None
        )
        issues = startup_issues(_production_platform(self.root), engine)
        self.assertTrue(any("LAYOUT_SERVICE_URL" in issue for issue in issues), issues)


class MigrationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.url = f"sqlite:///{(self.root / 'gate.db').as_posix()}"
        self.engine = build_engine(
            PlatformSettings(
                data_dir=self.root,
                database_url=self.url,
                secret_key="test",
                upload_dir=self.root / "uploads",
                engine_data_dir=self.root / "engine",
                engine_root=ENGINE_DIR,
            )
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self.tmp.cleanup()

    def _head(self) -> str:
        config = Config(str(API_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(API_DIR / "alembic"))
        return ScriptDirectory.from_config(config).get_current_head() or ""

    def test_empty_database_fails(self) -> None:
        with self.assertRaises(RuntimeError):
            verify_migrations(self.engine)

    def test_matching_head_passes(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
                {"v": self._head()},
            )
        verify_migrations(self.engine)

    def test_mismatched_revision_fails(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            )
            connection.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('outdated')")
            )
        with self.assertRaises(RuntimeError):
            verify_migrations(self.engine)


if __name__ == "__main__":
    unittest.main()
