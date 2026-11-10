import json
import tempfile
import unittest
from pathlib import Path

from metal_doc_agent.review import FeedbackStore, ReviewEvent
from tools.feedback_sample import main, sample_events


def make_event(event_id: str, action: str = "edit") -> ReviewEvent:
    return ReviewEvent(
        event_id=event_id,
        doc_id="doc-1",
        field_path="records.rec-1.properties.Rm",
        action=action,
        old_value={"value": 500.0},
        new_value={"value": 520.0} if action == "edit" else None,
        reason="核对原文",
        reviewer="reviewer-1",
    )


class FeedbackSampleTests(unittest.TestCase):
    def test_sampling_is_deterministic(self) -> None:
        events = [make_event(f"rev-{index}") for index in range(4)]
        first = [event.event_id for event in sample_events(events, rate=0.5, limit=10, seed="m4")]
        second = [
            event.event_id
            for event in sample_events(
                list(reversed(events)), rate=0.5, limit=10, seed="m4"
            )
        ]
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)

    def test_report_and_accuracy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = FeedbackStore(root / "feedback")
            self.assertTrue(store.append(make_event("rev-a")))
            self.assertTrue(store.append(make_event("rev-b", action="reject")))

            annotations = root / "annotations.jsonl"
            annotations.write_text(
                "\n".join(
                    [
                        json.dumps({"event_id": "rev-a", "verdict": "correct"}),
                        json.dumps({"event_id": "rev-b", "verdict": "incorrect"}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            empty_runs = root / "runs"
            empty_runs.mkdir()
            out = root / "feedback.json"
            md = root / "feedback.md"
            samples = root / "samples.jsonl"

            code = main(
                [
                    "--feedback",
                    str(root / "feedback"),
                    "--runs",
                    str(empty_runs),
                    "--annotations",
                    str(annotations),
                    "--rate",
                    "1.0",
                    "--limit",
                    "10",
                    "--samples",
                    str(samples),
                    "--out",
                    str(out),
                    "--md",
                    str(md),
                ]
            )
            self.assertEqual(code, 0)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["events"], 2)
            self.assertEqual(report["sampled"], 2)
            self.assertEqual(report["annotated"], 2)
            self.assertEqual(report["accuracy"], 0.5)
            self.assertEqual(report["correct"], 1)
            self.assertEqual(report["incorrect"], 1)
            self.assertEqual(len(samples.read_text(encoding="utf-8").strip().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
