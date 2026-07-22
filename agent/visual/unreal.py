import argparse
import json
import os
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request


STATE_PROFILES = {
    "created": {
        "ShellStrength": 3.0,
        "BreathSpeed": 0.12,
        "BreathExpansion": 0.35,
        "ShellColor": (0.35, 0.55, 0.7)
    },
    "booting": {
        "ShellStrength": 12.0,
        "BreathSpeed": 0.35,
        "BreathExpansion": 0.7,
        "ShellColor": (0.7, 0.9, 1.0)
    },
    "wake_detected": {
        "ShellStrength": 20.0,
        "BreathSpeed": 0.55,
        "BreathExpansion": 1.15,
        "ShellColor": (0.05, 0.85, 1.0)
    },
    "listening": {
        "ShellStrength": 18.0,
        "BreathSpeed": 0.45,
        "BreathExpansion": 0.95,
        "ShellColor": (0.04, 0.32, 1.0)
    },
    "transcribing": {
        "ShellStrength": 14.0,
        "BreathSpeed": 0.7,
        "BreathExpansion": 0.75,
        "ShellColor": (0.3, 0.12, 1.0)
    },
    "thinking": {
        "ShellStrength": 28.0,
        "BreathSpeed": 0.55,
        "BreathExpansion": 1.05,
        "ShellColor": (0.72, 0.08, 1.0)
    },
    "tool_started": {
        "ShellStrength": 35.0,
        "BreathSpeed": 0.8,
        "BreathExpansion": 1.25,
        "ShellColor": (1.0, 0.34, 0.03)
    },
    "tool_finished": {
        "ShellStrength": 14.0,
        "BreathSpeed": 0.3,
        "BreathExpansion": 0.6,
        "ShellColor": (0.08, 1.0, 0.42)
    },
    "speaking": {
        "ShellStrength": 22.0,
        "BreathSpeed": 0.65,
        "BreathExpansion": 1.2,
        "ShellColor": (0.05, 1.0, 0.18)
    },
    "autonomous": {
        "ShellStrength": 30.0,
        "BreathSpeed": 0.42,
        "BreathExpansion": 0.9,
        "ShellColor": (1.0, 0.78, 0.04)
    },
    "waiting_confirmation": {
        "ShellStrength": 18.0,
        "BreathSpeed": 0.22,
        "BreathExpansion": 0.72,
        "ShellColor": (1.0, 0.52, 0.08)
    },
    "recovering": {
        "ShellStrength": 24.0,
        "BreathSpeed": 0.75,
        "BreathExpansion": 1.35,
        "ShellColor": (1.0, 0.2, 0.02)
    },
    "service_error": {
        "ShellStrength": 42.0,
        "BreathSpeed": 0.9,
        "BreathExpansion": 1.45,
        "ShellColor": (1.0, 0.07, 0.01)
    },
    "error": {
        "ShellStrength": 45.0,
        "BreathSpeed": 1.2,
        "BreathExpansion": 1.7,
        "ShellColor": (1.0, 0.01, 0.16)
    },
    "idle": {
        "ShellStrength": 5.0,
        "BreathSpeed": 0.18,
        "BreathExpansion": 0.6,
        "ShellColor": (0.03, 0.62, 0.72)
    },
    "stopping": {
        "ShellStrength": 2.0,
        "BreathSpeed": 0.1,
        "BreathExpansion": 0.25,
        "ShellColor": (0.12, 0.18, 0.32)
    },
    "stopped": {
        "ShellStrength": 0.0,
        "BreathSpeed": 0.0,
        "BreathExpansion": 0.0,
        "ShellColor": (0.0, 0.0, 0.0)
    }
}


def _enabled(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class UnrealRemoteControlSink:
    def __init__(
        self,
        enabled=None,
        base_url=None,
        preset=None,
        target=None,
        function=None,
        property_name=None,
        component_path=None,
        parameter=None,
        timeout=None,
        opener=None
    ):
        if enabled is None:
            enabled = _enabled(os.getenv("ENTITY_UNREAL_ENABLED", ""))

        self.enabled = bool(enabled)
        self.base_url = (
            base_url
            or os.getenv("ENTITY_UNREAL_REMOTE_URL")
            or "http://127.0.0.1:30010"
        ).rstrip("/")
        self.preset = (
            preset
            or os.getenv("ENTITY_UNREAL_PRESET")
            or "EntityOrb"
        )
        self.target = (
            target
            or os.getenv("ENTITY_UNREAL_TARGET")
            or "component_scalar"
        ).strip().lower()
        self.function = (
            function
            or os.getenv("ENTITY_UNREAL_FUNCTION")
            or "SetEntityState"
        )
        self.property_name = (
            property_name
            or os.getenv("ENTITY_UNREAL_PROPERTY")
            or "Entity State"
        )
        self.component_path = (
            component_path
            or os.getenv("ENTITY_UNREAL_COMPONENT_PATH")
            or "/Game/Maps/UEDPIE_0_EntityRoomTest.EntityRoomTest:"
            "PersistentLevel.BP_EntityOrb_C_0.Shell"
        )
        self.parameter = (
            parameter
            or os.getenv("ENTITY_UNREAL_STATE_PARAMETER")
            or "NewState"
        )
        self.timeout = float(
            timeout
            or os.getenv("ENTITY_UNREAL_TIMEOUT_SECONDS")
            or "0.5"
        )
        self.opener = opener or urllib.request.urlopen
        self._queue = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._thread = None
        self._last_error = None

    def start(self):
        if not self.enabled:
            return

        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="entity-unreal-bridge",
            daemon=True
        )
        self._thread.start()

    def publish(self, event):
        if not self.enabled:
            return

        payload = dict(event)

        try:
            self._queue.put_nowait(payload)
            return
        except queue.Full:
            pass

        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:
            pass

        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            pass

    def deliver(self, event):
        state = str(event.get("state", "idle"))

        if self.target == "component_scalar":
            profile = STATE_PROFILES.get(state, STATE_PROFILES["idle"])

            for name, value in profile.items():
                if isinstance(value, tuple):
                    delivered = self._deliver_component_vector(name, value)
                else:
                    delivered = self._deliver_component_scalar(name, value)

                if not delivered:
                    return False

            return True

        if self.target == "function":
            body = {
                "Parameters": {self.parameter: state},
                "GenerateTransaction": False
            }
        else:
            body = {
                "PropertyValue": state,
                "GenerateTransaction": False
            }

        return self._deliver_request(
            urllib.request.Request(
                self._endpoint(),
                data=json.dumps(body).encode("utf-8"),
                method="PUT",
                headers={"Content-Type": "application/json"}
            )
        )

    def _deliver_component_scalar(self, name, value):
        body = {
            "ObjectPath": self.component_path,
            "FunctionName": "SetScalarParameterValueOnMaterials",
            "Parameters": {
                "ParameterName": name,
                "ParameterValue": value
            },
            "GenerateTransaction": False
        }
        request = urllib.request.Request(
            f"{self.base_url}/remote/object/call",
            data=json.dumps(body).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"}
        )
        return self._deliver_request(request)

    def _deliver_component_vector(self, name, value):
        body = {
            "ObjectPath": self.component_path,
            "FunctionName": "SetVectorParameterValueOnMaterials",
            "Parameters": {
                "ParameterName": name,
                "ParameterValue": {
                    "X": value[0],
                    "Y": value[1],
                    "Z": value[2]
                }
            },
            "GenerateTransaction": False
        }
        request = urllib.request.Request(
            f"{self.base_url}/remote/object/call",
            data=json.dumps(body).encode("utf-8"),
            method="PUT",
            headers={"Content-Type": "application/json"}
        )
        return self._deliver_request(request)

    def _deliver_request(self, request):
        try:
            with self.opener(request, timeout=self.timeout) as response:
                response.read()
        except (OSError, urllib.error.URLError) as exc:
            message = self._error_message(exc)

            if message != self._last_error:
                print(message)
                self._last_error = message

            return False

        if self._last_error:
            print("Unreal visual bridge connected.")

        self._last_error = None
        return True

    def close(self):
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=max(1.0, self.timeout + 0.5))
            self._thread = None

    def _run(self):
        while not self._stop_event.is_set():
            try:
                event = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                self.deliver(event)
            finally:
                self._queue.task_done()

    def _endpoint(self):
        preset = urllib.parse.quote(self.preset, safe="")

        if self.target == "function":
            function = urllib.parse.quote(self.function, safe="")
            return (
                f"{self.base_url}/remote/preset/{preset}/function/{function}"
            )

        property_name = urllib.parse.quote(self.property_name, safe="")
        return (
            f"{self.base_url}/remote/preset/{preset}/property/"
            f"{property_name}"
        )

    def _error_message(self, error):
        if isinstance(error, urllib.error.HTTPError):
            return (
                "Unreal visual bridge failed: Remote Control returned "
                f"HTTP {error.code}."
            )

        return "Unreal visual bridge waiting for Unreal Remote Control."


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Send a lifecycle state to the Unreal Entity orb."
    )
    parser.add_argument("state")
    parser.add_argument("--url", default="http://127.0.0.1:30010")
    parser.add_argument("--preset", default="EntityOrb")
    parser.add_argument(
        "--target",
        choices=("component_scalar", "property", "function"),
        default="component_scalar"
    )
    parser.add_argument("--function", default="SetEntityState")
    parser.add_argument("--property", default="Entity State")
    parser.add_argument(
        "--component-path",
        default=(
            "/Game/Maps/UEDPIE_0_EntityRoomTest.EntityRoomTest:"
            "PersistentLevel.BP_EntityOrb_C_0.Shell"
        )
    )
    args = parser.parse_args(argv)
    sink = UnrealRemoteControlSink(
        enabled=True,
        base_url=args.url,
        preset=args.preset,
        target=args.target,
        function=args.function,
        property_name=args.property,
        component_path=args.component_path
    )

    if not sink.deliver({"state": args.state}):
        raise SystemExit(1)

    print(f"Sent Unreal visual state: {args.state}")


if __name__ == "__main__":
    main()
