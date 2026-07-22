import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from agent.visual import VISUAL_MODES, create_visual_sink
from agent.visual.web import WebVisualSink


class VisualInterfaceTests(unittest.TestCase):
    def test_visual_factory_supports_all_public_modes(self):
        self.assertEqual(("2d", "3d", "unreal"), VISUAL_MODES)
        self.assertEqual("2d", create_visual_sink("2D").mode)
        self.assertEqual("3d", create_visual_sink(" 3d ").mode)
        self.assertTrue(create_visual_sink("unreal").enabled)

        with self.assertRaises(ValueError):
            create_visual_sink("hologram")

    def test_2d_server_serves_interface_and_keeps_latest_event(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            interface = project_root / "visual_mockup"
            interface.mkdir()
            (interface / "index.html").write_text(
                "<!doctype html><title>Entity test</title>",
                encoding="utf-8"
            )
            sink = WebVisualSink(
                "2d",
                host="127.0.0.1",
                port=0,
                open_browser=False,
                project_root=project_root
            )

            try:
                sink.start()
                with urllib.request.urlopen(sink.url, timeout=2) as response:
                    page = response.read().decode("utf-8")
                    self.assertEqual("no-store", response.headers["Cache-Control"])
                self.assertIn("Entity test", page)

                event = {"state": "thinking", "details": {"tool": "research"}}
                sink.publish(event)
                self.assertEqual(event, sink.events.latest)

                with urllib.request.urlopen(sink.url + "events", timeout=2) as response:
                    line = response.readline().decode("utf-8")
                self.assertEqual(event, json.loads(line.removeprefix("data: ")))
            finally:
                sink.close()

    def test_web_sink_can_restart_cleanly(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory)
            interface = project_root / "visual_mockup"
            interface.mkdir()
            (interface / "index.html").write_text("ok", encoding="utf-8")
            sink = WebVisualSink(
                "2d", host="127.0.0.1", port=0, open_browser=False,
                project_root=project_root
            )

            sink.start()
            sink.close()
            sink.start()
            try:
                self.assertFalse(sink.events.closed)
            finally:
                sink.close()

    def test_3d_build_refreshes_dependencies_when_lock_changes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "package.json").write_text("{}", encoding="utf-8")
            (source / "package-lock.json").write_text(
                '{"lockfileVersion": 3}', encoding="utf-8"
            )
            vite = source / "node_modules" / ".bin" / "vite"
            vite.parent.mkdir(parents=True)
            vite.touch()
            sink = WebVisualSink("3d", open_browser=False)

            def completed(command, **kwargs):
                if command == ["node", "--version"]:
                    return mock.Mock(stdout="v18.19.1\n", returncode=0)
                return mock.Mock(stdout="", stderr="", returncode=0)

            with mock.patch(
                "agent.visual.web.subprocess.run", side_effect=completed
            ) as run:
                sink._build_three_interface(source)
                sink._build_three_interface(source)

            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(1, commands.count(["npm", "ci"]))
            self.assertEqual(2, commands.count(["npm", "run", "build"]))

    def test_3d_build_rejects_unsupported_node_version(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            (source / "package.json").write_text("{}", encoding="utf-8")
            sink = WebVisualSink("3d", open_browser=False)

            result = mock.Mock(stdout="v16.20.2\n", returncode=0)
            with mock.patch(
                "agent.visual.web.subprocess.run", return_value=result
            ):
                with self.assertRaisesRegex(RuntimeError, "18 or newer"):
                    sink._build_three_interface(source)


if __name__ == "__main__":
    unittest.main()
