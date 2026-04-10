from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Protocol


API_HOSTNAME = "api.socialwiiv.com"
AZURE_REGION = "South Africa North"
TLS_VERSION = "TLS 1.2"


class CelbuxClient(Protocol):
    def create_voucher(self, mobile_number: str, points: int, metadata: Dict[str, str]) -> str:
        """TT 1 - Create Merchant Voucher."""

    def send_otp(self, mobile_number: str) -> str:
        """TT 2011 - Send OTP."""

    def create_wallet(self, mobile_number: str, first_name: str, last_name: str) -> str:
        """TT 2082 - Create Wallet."""

    def merchant_accepts_voucher(self, voucher_id: str, merchant_id: str) -> bool:
        """TT 4 - Merchant Accepts Voucher."""

    def settle_voucher(self, voucher_id: str, merchant_id: str) -> str:
        """TT 18 - Settle Voucher."""


class SituationRoomClient(Protocol):
    def publish(self, event_name: str, payload: Dict[str, str]) -> None:
        """Sync metadata for ROI/cultural momentum tracking."""


@dataclass
class UserProfile:
    first_name: str
    last_name: str
    mobile_number: str
    age: int
    wallet_id: str | None = None
    points: int = 0
    tier: str = "Bronze"


class InMemorySituationRoom:
    def __init__(self) -> None:
        self.events: List[Dict[str, Dict[str, str]]] = []

    def publish(self, event_name: str, payload: Dict[str, str]) -> None:
        self.events.append({"event_name": event_name, "payload": payload})


class MockCelbuxClient:
    def __init__(self) -> None:
        self.issued_vouchers: List[Dict[str, str | int]] = []
        self.wallets: Dict[str, str] = {}

    def create_voucher(self, mobile_number: str, points: int, metadata: Dict[str, str]) -> str:
        voucher_id = f"VCHR-{len(self.issued_vouchers) + 1:05d}"
        self.issued_vouchers.append(
            {
                "voucher_id": voucher_id,
                "mobile_number": mobile_number,
                "points": points,
                "metadata": json.dumps(metadata, sort_keys=True),
            }
        )
        return voucher_id

    def send_otp(self, mobile_number: str) -> str:
        return f"OTP-SENT:{mobile_number}"

    def create_wallet(self, mobile_number: str, first_name: str, last_name: str) -> str:
        wallet_id = f"WLT-{mobile_number[-6:]}"
        self.wallets[mobile_number] = wallet_id
        return wallet_id

    def merchant_accepts_voucher(self, voucher_id: str, merchant_id: str) -> bool:
        return bool(voucher_id and merchant_id)

    def settle_voucher(self, voucher_id: str, merchant_id: str) -> str:
        return f"SETTLED:{voucher_id}:{merchant_id}"


class VayaRewardOrchestrator:
    def __init__(
        self,
        shared_secret: str,
        celbux_client: CelbuxClient,
        situation_room: SituationRoomClient,
    ) -> None:
        self.shared_secret = shared_secret.encode("utf-8")
        self.celbux = celbux_client
        self.situation_room = situation_room
        self.users: Dict[str, UserProfile] = {}

    def register_local_user(self, user: UserProfile) -> None:
        self.users[user.mobile_number] = user

    def verify_hmac(self, payload: Dict[str, str], signature: str) -> bool:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        computed = hmac.new(self.shared_secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, signature)

    def _calc_tier(self, points: int) -> str:
        if points >= 5000:
            return "Gold"
        if points >= 2000:
            return "Silver"
        return "Bronze"

    def execute_programmatic_reward_for_verified_purchase(
        self,
        till_slip_event: Dict[str, str],
        signature: str,
    ) -> Dict[str, str]:
        if not self.verify_hmac(till_slip_event, signature):
            raise PermissionError("Invalid HMAC signature for till-slip event.")

        user = self.users[till_slip_event["mobile_number"]]
        points_awarded = int(till_slip_event.get("points", "50"))
        voucher_id = self.celbux.create_voucher(
            mobile_number=user.mobile_number,
            points=points_awarded,
            metadata={
                "transaction_type": "TT1",
                "product": till_slip_event["product"],
                "store_name": till_slip_event["store_name"],
                "time": till_slip_event.get("time", datetime.now(timezone.utc).isoformat()),
                "location": till_slip_event["location"],
            },
        )

        user.points += points_awarded
        user.tier = self._calc_tier(user.points)

        self.situation_room.publish(
            event_name="verified_purchase_reward",
            payload={
                "mobile_number": user.mobile_number,
                "voucher_id": voucher_id,
                "lifetime_points": str(user.points),
                "tier": user.tier,
                "product": till_slip_event["product"],
                "store_name": till_slip_event["store_name"],
                "time": till_slip_event.get("time", datetime.now(timezone.utc).isoformat()),
                "location": till_slip_event["location"],
            },
        )

        return {
            "status": "rewarded",
            "voucher_id": voucher_id,
            "tier": user.tier,
            "lifetime_points": str(user.points),
            "host": API_HOSTNAME,
            "transport": TLS_VERSION,
        }

    def automate_vaya_identity_and_wallet_provisioning(
        self,
        first_name: str,
        last_name: str,
        mobile_number: str,
        age: int,
        welcome_points: int = 100,
    ) -> Dict[str, str]:
        otp_status = self.celbux.send_otp(mobile_number)
        if age < 18:
            raise PermissionError("Age gate failed: user must be 18+.")

        wallet_id = self.celbux.create_wallet(mobile_number, first_name, last_name)
        profile = UserProfile(
            first_name=first_name,
            last_name=last_name,
            mobile_number=mobile_number,
            age=age,
            wallet_id=wallet_id,
            points=welcome_points,
            tier=self._calc_tier(welcome_points),
        )
        self.users[mobile_number] = profile

        self.situation_room.publish(
            event_name="wallet_provisioned",
            payload={
                "mobile_number": mobile_number,
                "wallet_id": wallet_id,
                "otp_status": otp_status,
                "welcome_points": str(welcome_points),
                "tier": profile.tier,
                "region": AZURE_REGION,
            },
        )

        return {
            "status": "provisioned",
            "wallet_id": wallet_id,
            "welcome_points": str(welcome_points),
            "tier": profile.tier,
        }

    def process_vaya_play_winner_reward_and_merchant_settlement(
        self,
        mobile_number: str,
        merchant_id: str,
        dwell_time_seconds: int,
        social_score: int,
        reward_points: int = 75,
    ) -> Dict[str, str]:
        user = self.users[mobile_number]
        voucher_id = self.celbux.create_voucher(
            mobile_number=mobile_number,
            points=reward_points,
            metadata={"transaction_type": "TT1", "source": "vaya_play_win"},
        )
        accepted = self.celbux.merchant_accepts_voucher(voucher_id, merchant_id)
        if not accepted:
            raise RuntimeError("Voucher acceptance failed at merchant.")

        settlement_id = self.celbux.settle_voucher(voucher_id, merchant_id)
        user.points += reward_points
        user.tier = self._calc_tier(user.points)

        self.situation_room.publish(
            event_name="cultural_momentum",
            payload={
                "mobile_number": mobile_number,
                "voucher_id": voucher_id,
                "merchant_id": merchant_id,
                "settlement_id": settlement_id,
                "dwell_time_seconds": str(dwell_time_seconds),
                "social_score": str(social_score),
                "updated_points": str(user.points),
                "tier": user.tier,
            },
        )

        return {
            "status": "settled",
            "voucher_id": voucher_id,
            "settlement_id": settlement_id,
            "tier": user.tier,
            "updated_points": str(user.points),
        }
