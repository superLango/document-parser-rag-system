"""M5 productionization: infra manifests, observability, backup and security assets."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "infra" / "k8s"
PROJECT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(PROJECT))
from metal_doc_agent.observability import engine_metrics, readiness, render_metric  # noqa: E402
from metal_doc_agent.jobs import JobStore  # noqa: E402


def _docs(path: Path) -> list[dict]:
    return [doc for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")) if doc]


class KubernetesManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifests: list[dict] = []
        for path in sorted(K8S.glob("*.yaml")):
            cls.manifests.extend(_docs(path))

    def test_required_kinds_exist(self) -> None:
        kinds = {doc.get("kind") for doc in self.manifests}
        for kind in (
            "Namespace",
            "ConfigMap",
            "Secret",
            "PersistentVolumeClaim",
            "Deployment",
            "Service",
            "Ingress",
            "HorizontalPodAutoscaler",
            "PodDisruptionBudget",
            "NetworkPolicy",
        ):
            self.assertIn(kind, kinds, kind)

    def test_deployments_are_rolling_and_probed(self) -> None:
        deployments = [doc for doc in self.manifests if doc.get("kind") == "Deployment"]
        self.assertGreaterEqual(len(deployments), 5)
        names = {doc["metadata"]["name"] for doc in deployments}
        self.assertIn("engine-api", names)
        self.assertIn("platform-api", names)
        self.assertIn("worker-prod", names)
        self.assertIn("worker-explore", names)
        self.assertIn("worker-human", names)
        for doc in deployments:
            spec = doc["spec"]
            self.assertEqual(spec["strategy"]["type"], "RollingUpdate", doc["metadata"]["name"])
            pod = spec["template"]["spec"]
            self.assertIn("securityContext", pod, doc["metadata"]["name"])
            for container in pod["containers"]:
                self.assertIn("resources", container, doc["metadata"]["name"])
                self.assertTrue(
                    container.get("readinessProbe") or container.get("livenessProbe"),
                    doc["metadata"]["name"],
                )

    def test_ingress_autoscale_and_network_policy(self) -> None:
        ingress = next(doc for doc in self.manifests if doc.get("kind") == "Ingress")
        self.assertEqual(ingress["spec"]["ingressClassName"], "nginx")
        self.assertGreaterEqual(len(ingress["spec"]["rules"]), 2)
        hpas = [doc for doc in self.manifests if doc.get("kind") == "HorizontalPodAutoscaler"]
        self.assertGreaterEqual(len(hpas), 2)
        pdbs = [doc for doc in self.manifests if doc.get("kind") == "PodDisruptionBudget"]
        self.assertGreaterEqual(len(pdbs), 2)
        policies = [doc for doc in self.manifests if doc.get("kind") == "NetworkPolicy"]
        self.assertGreaterEqual(len(policies), 3)

    def test_canary_overlay_and_model_plane(self) -> None:
        overlay = K8S / "overlays" / "canary" / "kustomization.yaml"
        self.assertTrue(overlay.exists())
        data = yaml.safe_load(overlay.read_text(encoding="utf-8"))
        self.assertEqual(data["images"][0]["newTag"], "canary")
        self.assertTrue((K8S / "model-plane" / "README.md").exists())


class MonitoringTests(unittest.TestCase):
    def test_alert_rules_and_dashboard(self) -> None:
        rules = yaml.safe_load(
            (ROOT / "infra" / "monitoring" / "prometheus-rules.yaml").read_text(
                encoding="utf-8"
            )
        )
        alerts = {
            rule["alert"]
            for group in rules["groups"]
            for rule in group["rules"]
            if "alert" in rule
        }
        for name in (
            "EngineApiDown",
            "EngineJobBacklog",
            "EngineJobFailureRate",
            "ExploreBacklog",
            "ModelExtractDown",
        ):
            self.assertIn(name, alerts)
        dashboard = json.loads(
            (ROOT / "infra" / "monitoring" / "grafana-dashboard.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertGreaterEqual(len(dashboard["panels"]), 5)


class DeliveryAssetTests(unittest.TestCase):
    def test_docker_and_compose(self) -> None:
        docker = ROOT / "infra" / "docker"
        for name in ("Dockerfile.engine", "Dockerfile.api", "Dockerfile.web", "nginx.conf"):
            self.assertTrue((docker / name).exists(), name)
        compose = yaml.safe_load((docker / "compose.yaml").read_text(encoding="utf-8"))
        services = set(compose["services"])
        self.assertTrue(
            {"postgres", "platform-api", "engine-api", "worker-prod", "worker-explore", "web"}
            <= services
        )

    def test_backup_and_docs(self) -> None:
        backup = (ROOT / "infra" / "backup" / "backup.sh").read_text(encoding="utf-8")
        restore = (ROOT / "infra" / "backup" / "restore.sh").read_text(encoding="utf-8")
        self.assertIn("pg_dump", backup)
        self.assertIn("pg_restore", restore)
        for doc in ("runbook.md", "security.md", "slo.md"):
            self.assertTrue((ROOT / "docs" / doc).exists(), doc)

    def test_secret_scan_passes(self) -> None:
        import importlib.util

        path = ROOT / "infra" / "security" / "check_secrets.py"
        spec = importlib.util.spec_from_file_location("check_secrets", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        self.assertEqual(module.scan(ROOT), [])


class ObservabilityTests(unittest.TestCase):
    def test_metric_rendering(self) -> None:
        text = "\n".join(render_metric("engine_jobs", {"status": "queued"}, 3))
        self.assertIn("# TYPE engine_jobs gauge", text)
        self.assertIn('engine_jobs{status="queued"} 3', text)

    def test_engine_metrics_from_store(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(Path(tmp) / "jobs")
            out_dir = Path(tmp) / "jobs" / "job1"
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "metrics.json").write_text(
                '{"pipeline_seconds": 42.5}', encoding="utf-8"
            )
            state, _created = store.reserve(
                job_id="job1",
                idempotency_key="key1",
                source_name="doc.md",
                source_sha256="sha",
                doc_path=str(Path(tmp) / "doc.md"),
                options={},
            )
            queue_dir = Path(tmp) / "queues"
            queue_dir.mkdir(parents=True, exist_ok=True)
            text = engine_metrics(store, queue_dir)
            self.assertEqual(text.count("# HELP engine_jobs"), 1)
            self.assertIn("engine_pipeline_seconds_bucket", text)
            self.assertIn('engine_pipeline_seconds_bucket{le="60"} 1', text)
            self.assertIn('engine_queue_items{lane="production"} 0', text)
            ready = readiness(ROOT / "metal-doc-agent", Path(tmp) / "engine")
            self.assertEqual(ready["status"], "ok")
            self.assertTrue(ready["checks"]["data_dir_writable"])


class EngineApiOpsTests(unittest.TestCase):
    def test_metrics_and_readiness_endpoints(self) -> None:
        try:
            from fastapi.testclient import TestClient

            from metal_doc_agent.api import create_app
            from metal_doc_agent.settings import Settings
        except ImportError:  # pragma: no cover - optional dependency
            self.skipTest("fastapi not installed")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(
                project_root=PROJECT,
                data_dir=Path(tmp),
                ocr_backend="mock",
                extractor_backend="mock",
                glm_ocr_base_url=None,
                glm_ocr_model="GLM-OCR",
                qwen_base_url=None,
                qwen_model="Qwen3.5-9B",
                api_key=None,
                request_timeout=10.0,
            )
            client = TestClient(create_app(settings))
            self.assertEqual(client.get("/ready").status_code, 200)
            metrics = client.get("/metrics")
            self.assertEqual(metrics.status_code, 200)
            self.assertIn("engine_jobs", metrics.text)


if __name__ == "__main__":
    unittest.main()
