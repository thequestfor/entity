import io
import os
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from agent.routes import RoutePlanner


class FakeStore:
    def get_geocode(self, query, provider):
        return None

    def set_geocode(self, *args, **kwargs):
        return None


class RoutePlannerTests(unittest.TestCase):
    def planner(self):
        env = {
            "ENTITY_ROUTES_PROVIDER": "tomtom",
            "ENTITY_TOMTOM_API_KEY": "test-key",
            "ENTITY_HOME_ADDRESS": "Home",
            "ENTITY_DEFAULT_TRAVEL_MODE": "driving-car",
        }
        with patch.dict(os.environ, env, clear=False):
            return RoutePlanner(store=FakeStore())

    def test_tomtom_route_uses_supported_query_parameters(self):
        planner = self.planner()
        paths = []
        planner.geocode = lambda query: (
            [-80.75, 35.0] if query == "Home" else [-80.94, 35.2]
        )

        def response(path):
            paths.append(path)
            return {
                "routes": [
                    {
                        "summary": {
                            "travelTimeInSeconds": 1800,
                            "lengthInMeters": 40000,
                            "trafficDelayInSeconds": 120,
                        }
                    }
                ]
            }

        planner._get_tomtom_json = response

        estimate = planner.estimate("Home", "Airport")
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(paths[0]).query)

        self.assertNotIn("instructionsType", query)
        self.assertEqual(["all"], query["computeTravelTimeFor"])
        self.assertEqual(["true"], query["traffic"])
        self.assertEqual(30, estimate.duration_minutes)
        self.assertEqual(120, estimate.traffic_delay_seconds)

    def test_tomtom_coordinates_are_formatted_as_latitude_longitude(self):
        planner = self.planner()

        self.assertEqual("35.0,-80.75", planner._tomtom_coordinate_text([-80.75, 35.0]))

    def test_http_error_includes_provider_detail_without_request_url(self):
        planner = self.planner()
        error = urllib.error.HTTPError(
            url="https://api.tomtom.com/path?key=secret",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(
                b'{"detailedError":{"message":"Invalid parameter"}}'
            ),
        )

        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(
                RuntimeError,
                r"failed \(400\): Invalid parameter",
            ) as raised:
                planner._open_json("request")

        self.assertNotIn("secret", str(raised.exception))

    def test_live_travel_time_is_labeled_as_provider_verified(self):
        planner = self.planner()
        planner.estimate = lambda origin, destination: type(
            "Estimate",
            (),
            {
                "duration_minutes": 12,
                "distance_miles": 6.2,
                "traffic_delay_seconds": 0
            }
        )()

        response = planner.travel_time("Home", "Clinic")

        self.assertIn("TomTom live traffic", response)
        self.assertIn("12 minutes", response)
        self.assertIn("No traffic delay reported", response)


if __name__ == "__main__":
    unittest.main()
