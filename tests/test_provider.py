"""Contract, recovery and charging invariants against recorded CLI schemas."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from libtv_provider import LibTVProvider, json_objects, save_json
from provider import ProviderError, run_jobs
from asr_beats import segment_words
from pipeline import plan

MODELS = json.loads((Path(__file__).parent / "fixtures/libtv-models.json").read_text(encoding="utf-8"))


class CLI:
    def __init__(self):
        self.nodes, self.calls, self.runs = {}, [], 0
        self.lose_receipt = False
        self.pending = False

    def __call__(self, command, **kwargs):
        args = command[1:]
        self.calls.append(args)
        if args[:2] == ["model", "search"]:
            result = {"matches": [{"modelName": n, "modelKey": v["modelKey"]}
                                  for n, v in MODELS.items() if v["kind"] == args[-1]]}
        elif args[0] == "model":
            result = {"schema": MODELS[args[1]]["schema"]}
        elif args[:2] == ["node", "list"]:
            result = {"nodes": [{"id": key, "name": n["data"]["name"]} for key, n in self.nodes.items()]}
        elif args[:2] == ["node", "create"]:
            key = f"node-{len(self.nodes)}"
            fields = {}
            for i, value in enumerate(args):
                if value == "-s":
                    k, v = args[i+1].split("=", 1)
                    try:
                        v = json.loads(v)
                    except ValueError:
                        pass
                    fields[k] = v
            node = {"nodeKey": key, "nodeType": args[args.index("-t")+1],
                    "data": {"name": args[2], "url": [], "params": fields}}
            self.nodes[key] = node
            result = {"newNodeKey": key, "reactFlowNode": {"id": key}} if "--left" in args else node
        elif args[0] == "node":
            key = args[1]
            node = self.nodes[key]
            if "--run" in args:
                self.runs += 1
                if not self.pending:
                    node["data"].update(url=["https://example.invalid/result"],
                                        taskInfo={"status": 2, "loading": False})
                if self.lose_receipt:
                    raise OSError("connection lost after acceptance")
            result = node
        else:
            raise AssertionError(args)
        return subprocess.CompletedProcess(command, 0, json.dumps(result), "")


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cli = CLI()
        self.prov = LibTVProvider(self.tmp.name, {"libtv": {"project_id": "test"}}, self.cli)

    def tearDown(self):
        self.tmp.cleanup()

    def test_json_stream_handles_logs_and_multiple_receipts(self):
        values = json_objects('log\n{"task": 1}\nprogress\n{"task":2}\n')
        self.assertEqual([o["task"] for o in values], [1, 2])

    def test_image_flat_parameters_and_single_output(self):
        _, fields = self.prov.normalize("General image V2", "image", "test",
                                        {"resolution": "1k", "aspect_ratio": "16:9"}, [])
        self.assertEqual(fields["quality"], "1K")
        self.assertEqual(fields["count"], 1)
        self.assertNotIn("settings.quality", fields)

    def test_tts_and_music_scenes_are_explicit(self):
        for model, scene in (("Minimax-speech-2.8-hd", "Text-to-Speech"), ("Eleven Music V3", "Music")):
            _, fields = self.prov.normalize(model, "audio", "test", {}, [])
            self.assertEqual(fields["scene"], scene)

    def test_reference_modes_and_edit_source_time(self):
        for kinds, expected in ((["image"], "singleImage2video"),
                                (["image", "audio"], "mixed2video"), (["video"], "videoEdit2video")):
            _, fields = self.prov.normalize("Seedance 2.5", "video", "test",
                                            {"duration": 4, "ratio": "16:9"},
                                            [{"kind": k, "node": str(i)} for i, k in enumerate(kinds)])
            self.assertEqual(fields["modeType"], expected)
            if expected == "videoEdit2video":
                self.assertEqual(fields["duration_auto"], 0)
                self.assertEqual(fields["ratio_auto"], "adaptive")
                self.assertNotIn("duration", fields)

    def test_invalid_duration_rejected_before_node_creation(self):
        with self.assertRaises(ProviderError):
            self.prov.submit_video("Seedance 2.5", "test", duration=2)
        self.assertFalse(self.cli.nodes)

    def test_completed_request_never_charges_twice(self):
        a = self.prov.submit_image("General image V2", "test", resolution="1k")
        b = self.prov.submit_image("General image V2", "test", resolution="1k")
        self.assertEqual(a, b)
        self.assertEqual(self.cli.runs, 1)

    def test_lost_receipt_recovers_same_completed_node(self):
        self.cli.lose_receipt = True
        with self.assertRaises(OSError):
            self.prov.submit_image("General image V2", "test")
        self.cli.lose_receipt = False
        key = self.prov.submit_image("General image V2", "test")
        self.assertEqual(self.prov.get_status(key)["status"], "completed")
        self.assertEqual(self.cli.runs, 1)

    def test_manually_replaced_output_is_not_mistaken_for_cached_job(self):
        self.prov.submit_image("General image V2", "test")
        self.cli.nodes['node-0']['data']['url']=['https://example.invalid/different']
        with self.assertRaisesRegex(ProviderError, 'output changed'):
            self.prov.submit_image("General image V2", "test")
        self.assertEqual(self.cli.runs,1)

    def test_unknown_pending_request_is_not_resubmitted(self):
        self.cli.pending = self.cli.lose_receipt = True
        with self.assertRaises(OSError):
            self.prov.submit_image("General image V2", "test")
        with self.assertRaises(ProviderError):
            self.prov.submit_image("General image V2", "test")
        self.assertEqual(self.cli.runs, 1)

    def test_connected_creation_receipt_and_reference_edge(self):
        # The runner is a local fake; no real permission or remote dispatch.
        self.prov.cfg["require_video_approval"] = False
        key = self.prov.submit_image("General image V2", "reference")
        ref = self.prov.get_status(key)["output"]
        self.prov.submit_video("Seedance 2.5", "animate", image=ref, duration=4)
        creations = [c for c in self.cli.calls if c[:2] == ["node", "create"]]
        self.assertIn("--left", creations[-1])
        self.assertEqual(self.cli.runs, 2)

    def test_unapproved_video_creates_no_remote_node(self):
        with self.assertRaisesRegex(ProviderError, "VIDEO_APPROVAL_REQUIRED"):
            self.prov.submit_video("Seedance 2.5", "test", duration=4)
        self.assertFalse(self.cli.nodes)
        self.assertEqual(self.cli.runs, 0)
        self.assertEqual(len(list(self.prov.state_dir.glob("video-plan-*.json"))), 1)

    def test_exact_video_approval_does_not_authorize_changed_prompt(self):
        from pipeline import approve_video
        with self.assertRaises(ProviderError):
            self.prov.submit_video("Seedance 2.5", "first", duration=4)
        path = next(self.prov.state_dir.glob("video-plan-*.json"))
        key = json.loads(path.read_text(encoding="utf-8"))["request_hash"]
        approve_video(self.tmp.name, key, "Offline test approval, fake CLI only")
        self.prov.submit_video("Seedance 2.5", "first", duration=4)
        with self.assertRaisesRegex(ProviderError, "VIDEO_APPROVAL_REQUIRED"):
            self.prov.submit_video("Seedance 2.5", "changed", duration=4)
        self.assertEqual(self.cli.runs, 1)

    def test_cross_project_reference_is_rejected(self):
        with self.assertRaises(ProviderError):
            self.prov.ref("libtv://other/node")

    def test_concurrent_writer_is_rejected(self):
        other = LibTVProvider(self.tmp.name, {"libtv": {"project_id": "test"}}, self.cli)
        with self.prov.lock():
            with self.assertRaises(ProviderError):
                with other.lock():
                    pass

    def test_batch_failure_cannot_return_partial_success(self):
        def fail():
            raise ProviderError("failed")
        with self.assertRaises(ProviderError):
            run_jobs(self.prov, {"one": lambda: self.prov.submit_image("General image V2", "one"), "two": fail})

    def test_asr_never_merges_over_duration_cap(self):
        words = [{"text": "字", "start": i, "end": i + 0.8} for i in range(12)]
        beats = segment_words(words, max_dur=4, min_dur=2)
        self.assertTrue(all(b["end"] - b["start"] <= 4 for b in beats))
        self.assertEqual(sum(len(b["text"].replace(" ", "")) for b in beats), len(words))

    def test_all_four_workflows_are_routed(self):
        base = {"beats": [{"shots": [{"id": "a"}]}]}
        self.assertIn("keyframes", plan(base))
        self.assertIn("croll_keyframes", plan({**base, "mode": "croll"}))
        self.assertEqual(plan({**base, "mode": "aroll"}), ["aroll_clips", "aroll_assemble"])
        base["beats"][0]["shots"][0]["kind"] = "host"
        self.assertLess(plan(base).index("audio"), plan(base).index("host_clips"))


if __name__ == "__main__":
    unittest.main()
