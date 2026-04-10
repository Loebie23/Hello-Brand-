import hashlib
import hmac
import json
import unittest

from src.vaya_orchestrator import InMemorySituationRoom, MockCelbuxClient, UserProfile, VayaRewardOrchestrator


class TestVayaRewardOrchestrator(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "top-secret"
        self.celbux = MockCelbuxClient()
        self.room = InMemorySituationRoom()
        self.orchestrator = VayaRewardOrchestrator(self.secret, self.celbux, self.room)

    def _signature(self, payload):
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    def test_verified_purchase_rewards_and_updates_tier(self):
        user = UserProfile("Tumi", "Dlamini", "+27820000001", age=29, points=1980)
        self.orchestrator.register_local_user(user)
        payload = {
            "mobile_number": user.mobile_number,
            "product": "Energy Drink",
            "store_name": "Soweto Spaza",
            "location": "Soweto",
            "points": "40",
        }

        result = self.orchestrator.execute_programmatic_reward_for_verified_purchase(
            payload,
            self._signature(payload),
        )

        self.assertEqual(result["status"], "rewarded")
        self.assertEqual(result["tier"], "Silver")
        self.assertEqual(result["lifetime_points"], "2020")
        self.assertEqual(self.room.events[-1]["event_name"], "verified_purchase_reward")

    def test_onboarding_blocks_underage_user(self):
        with self.assertRaises(PermissionError):
            self.orchestrator.automate_vaya_identity_and_wallet_provisioning(
                "Anele", "N", "+27820000002", age=17
            )

    def test_onboarding_creates_wallet_and_welcome_points(self):
        result = self.orchestrator.automate_vaya_identity_and_wallet_provisioning(
            "Anele", "N", "+27820000002", age=22
        )

        self.assertEqual(result["status"], "provisioned")
        self.assertTrue(result["wallet_id"].startswith("WLT-"))
        self.assertEqual(result["welcome_points"], "100")

    def test_play_winner_flow_rewards_and_settles(self):
        self.orchestrator.register_local_user(UserProfile("Boipelo", "K", "+27820000003", age=31, points=10))

        result = self.orchestrator.process_vaya_play_winner_reward_and_merchant_settlement(
            mobile_number="+27820000003",
            merchant_id="MERCH-1",
            dwell_time_seconds=90,
            social_score=74,
        )

        self.assertEqual(result["status"], "settled")
        self.assertIn("SETTLED:", result["settlement_id"])
        self.assertEqual(self.room.events[-1]["event_name"], "cultural_momentum")


if __name__ == "__main__":
    unittest.main()
