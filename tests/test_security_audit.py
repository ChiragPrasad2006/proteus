"""Independent security audit tests for the Proteus backend.

Proves (or disproves) the isolation and hardening claims:

* Account B must never reach Account A's contacts, cleaned corpus, profile,
  recipient profiles, chat sessions, or pending drafts through ANY endpoint -
  including the ``account_id`` body field on ``/api/chat/turn``.
* ``X-Account-ID`` is authoritative for chat turns.
* Malformed / adversarial request bodies never produce 500s.
* CORS allow-list contains only localhost dev origins.
* OAuth token directories are per-account and disjoint.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.automation import Contact
from backend.automation.contact_resolver import ContactResolver
from backend.automation.dispatcher import Dispatcher
from backend.config import Settings
from backend.main import create_app
from backend.schemas import DispatchRequest


class _SecurityAuditBase(unittest.TestCase):
    """Temp-dir app/client fixture (mirrors test_proteus_accounts conventions)."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.settings = Settings(
            local_user_data_dir=Path(self.temp_dir.name),
            profiler_mode="heuristic",
            model_name="not-installed-for-test",
        )
        self.app = create_app(settings=self.settings)
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _demo_seed(self) -> dict[str, dict]:
        response = self.client.post("/api/onboarding/demo-seed")
        self.assertEqual(response.status_code, 200, response.text)
        payload = self.client.get("/api/accounts").json()
        return {account["email"]: account for account in payload["accounts"]}

    def _ids(self) -> tuple[str, str]:
        accounts = self._demo_seed()
        return (
            accounts["sam@cloudscale.io"]["account_id"],
            accounts["chirag@expano.in"]["account_id"],
        )

    def _seed_contacts(self, account_id: str, contacts: list[Contact]) -> None:
        resolver = ContactResolver(self.settings.for_account(account_id).contacts_path)
        for contact in contacts:
            resolver.upsert_contact(contact)


class HeaderAuthorityTests(_SecurityAuditBase):
    """The X-Account-ID header must win over any account_id in the body."""

    def test_header_a_with_body_account_id_b_cannot_operate_on_b(self) -> None:
        a_id, b_id = self._ids()
        # Only account B knows "Manu".
        self._seed_contacts(
            b_id,
            [Contact(email="manu@expano.in", full_name="Manu Roy",
                     first_name="Manu", last_name="Roy", company_domain="expano.in")],
        )
        # Account A presents its own header but smuggles B's id in the body.
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": a_id},
            json={
                "user_message": "send an email to manu about the roadmap",
                "account_id": b_id,
            },
        )
        self.assertEqual(
            response.status_code,
            403,
            f"conflicting body account_id must be rejected, got: {response.text}",
        )

    def test_matching_header_and_body_still_works(self) -> None:
        a_id, _ = self._ids()
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": a_id},
            json={"user_message": "hello there", "account_id": a_id},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_body_account_id_without_header_still_selects_account(self) -> None:
        _, b_id = self._ids()
        self._seed_contacts(
            b_id,
            [Contact(email="manu@expano.in", full_name="Manu Roy",
                     first_name="Manu", last_name="Roy", company_domain="expano.in")],
        )
        response = self.client.post(
            "/api/chat/turn",
            json={"user_message": "send an email to manu", "account_id": b_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["resolutions"]["to"][0]["matched_email"],
            "manu@expano.in",
        )


class ChatSessionIsolationTests(_SecurityAuditBase):
    """Session reads resolve against the caller's own per-account sqlite file."""

    def test_b_cannot_read_a_session_detail(self) -> None:
        a_id, b_id = self._ids()
        created = self.client.post(
            "/api/chat/sessions", headers={"X-Account-ID": a_id}, json={"title": "secret"}
        )
        self.assertEqual(created.status_code, 200, created.text)
        session_id = created.json()["session_id"]

        response = self.client.get(
            f"/api/chat/sessions/{session_id}", headers={"X-Account-ID": b_id}
        )
        self.assertEqual(response.status_code, 404, response.text)
        self.assertNotIn("secret", response.text)

    def test_b_session_list_is_empty(self) -> None:
        a_id, b_id = self._ids()
        self.client.post(
            "/api/chat/sessions", headers={"X-Account-ID": a_id}, json={"title": "s"}
        )
        listed = self.client.get("/api/chat/sessions", headers={"X-Account-ID": b_id})
        self.assertEqual(listed.json()["sessions"], [])


class ApproveAndLearnIsolationTests(_SecurityAuditBase):
    """A pending draft stored under account A is invisible to account B."""

    def test_b_cannot_approve_a_pending_draft(self) -> None:
        a_id, b_id = self._ids()

        # Stage a pending draft in A's own sqlite via the app's own dispatcher
        # (same record shape the endpoint consumes), without needing OAuth.
        a_settings = self.settings.for_account(a_id)
        dispatcher = Dispatcher(a_settings)
        request = DispatchRequest(
            provider="demo",
            to=["someone@outside.example"],
            subject="Hi",
            intent_bullets="- say hi",
            auto_send=False,
        )
        dispatcher._save_pending_draft(
            draft_id="draft-a-1",
            request=request,
            draft="Hi someone,",
            profile_id="p1",
            recipient_profiles={},
        )

        # B tries to approve A's draft.
        response = self.client.post(
            "/api/email/approve-and-learn",
            headers={"X-Account-ID": b_id},
            json={
                "draft_id": "draft-a-1",
                "final_subject": "Hi",
                "final_body": "Hi someone, edited",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "FAILED")

        # A's draft must still be present and approvable by A.
        still_there = a_settings and dispatcher.load_pending_draft("draft-a-1")
        self.assertIsNotNone(still_there)
        approved = self.client.post(
            "/api/email/approve-and-learn",
            headers={"X-Account-ID": a_id},
            json={
                "draft_id": "draft-a-1",
                "final_subject": "Hi",
                "final_body": "Hi someone, edited",
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        body = approved.json()
        self.assertIn(body["status"], ("SENT", "FAILED"))
        self.assertIsInstance(body["extracted_rules"], list)


class CorpusEndpointIsolationTests(_SecurityAuditBase):
    """Cleaned corpus / retrieval / profile endpoints never leak across accounts."""

    def test_b_retrieval_sees_nothing_of_a(self) -> None:
        a_id, b_id = self._ids()
        # Index A's corpus directly into A's vector store (offline, cached model).
        try:
            from backend.retrieval import LanceDBVectorStore
            from backend.retrieval.embedder import LocalEmbedder
            from backend.storage import ProfileStore

            embedder = LocalEmbedder()
            embedder.load()
        except Exception:  # pragma: no cover - model missing
            self.skipTest("embedding model unavailable")

        a_settings = self.settings.for_account(a_id)
        cleaned = ProfileStore(a_settings).load_cleaned_emails()
        self.assertTrue(cleaned)
        LanceDBVectorStore(a_settings).index_emails(cleaned, embedder, force_recreate=True)

        # B searches for A's content by exact recipient and by subject text.
        search = self.client.post(
            "/api/retrieval/search",
            headers={"X-Account-ID": b_id},
            json={
                "query_text": "alex acme kickoff meeting notes",
                "recipient_email": "alex@acme.example",
                "k": 10,
                "min_word_count": 0,
            },
        )
        if search.status_code == 503:  # embedder unavailable at endpoint level
            return
        self.assertEqual(search.status_code, 200, search.text)
        payload = search.json()
        self.assertEqual(payload["total_indexed"], 0)
        leaked_bodies = [
            example["clean_body"]
            for example in payload["examples"]
            if "alex@acme.example" in example.get("recipient_email", "")
        ]
        self.assertEqual(leaked_bodies, [])

    def test_b_profile_404_and_distinct_after_build(self) -> None:
        a_id, b_id = self._ids()
        built = self.client.post(
            "/api/onboarding/build-profile", headers={"X-Account-ID": a_id}
        )
        self.assertEqual(built.status_code, 200, built.text)
        self.assertEqual(
            self.client.get("/api/profile", headers={"X-Account-ID": b_id}).status_code,
            404,
        )


class AdversarialInputTests(_SecurityAuditBase):
    """Malformed bodies get 4xx validation errors, never 500s or leaks."""

    CASES: list[tuple[str, dict, list[int]]] = [
        ("empty user_message", {"user_message": ""}, [422]),
        ("missing user_message", {}, [422]),
        ("wrong type user_message", {"user_message": 12345}, [422]),
        ("unknown field", {"user_message": "hi", "evil": "1"}, [422]),
        # Under a valid header a conflicting body id is 403 (header wins);
        # without a header an unresolvable body id is 404.
        (
            "traversal account_id",
            {"user_message": "hi", "account_id": "../admin"},
            [403, 404],
        ),
        (
            "traversal session_id",
            {"user_message": "hi", "session_id": "../../etc/passwd"},
            [200, 404],
        ),
        # pydantic v2 coerces "yes" -> True; both outcomes are safe (no 500, bool result).
        ("wrong type auto_send", {"user_message": "hi", "auto_send": "yes"}, [200, 422]),
    ]

    def test_chat_turn_adversarial_bodies(self) -> None:
        a_id, _ = self._ids()
        for label, payload, expected in self.CASES:
            with self.subTest(case=label):
                response = self.client.post(
                    "/api/chat/turn",
                    headers={"X-Account-ID": a_id},
                    json=payload,
                )
                self.assertIn(
                    response.status_code, expected, f"{label}: {response.text}"
                )
                self.assertNotEqual(response.status_code, 500)

    def test_oversized_message_is_handled(self) -> None:
        a_id, _ = self._ids()
        response = self.client.post(
            "/api/chat/turn",
            headers={"X-Account-ID": a_id},
            json={"user_message": "x" * 10_000},
        )
        self.assertEqual(response.status_code, 200, response.text[:300])
        self.assertNotEqual(response.status_code, 500)

    def test_accounts_endpoints_reject_bad_bodies(self) -> None:
        self._demo_seed()
        for label, method, url, payload in [
            ("switch unknown field", "post", "/api/accounts/switch",
             {"account_id": "x", "extra": 1}),
            ("switch wrong type", "post", "/api/accounts/switch",
             {"account_id": 12}),
        ]:
            with self.subTest(case=label):
                response = getattr(self.client, method)(url, json=payload)
                self.assertEqual(response.status_code, 422, response.text)

    def test_approve_and_learn_rejects_unknown_fields(self) -> None:
        a_id, _ = self._ids()
        response = self.client.post(
            "/api/email/approve-and-learn",
            headers={"X-Account-ID": a_id},
            json={"draft_id": "d", "final_subject": "s", "final_body": "b", "hack": 1},
        )
        self.assertEqual(response.status_code, 422, response.text)


class CorsTests(_SecurityAuditBase):
    """Only localhost dev origins are allowed; arbitrary origins get no CORS grant."""

    def test_disallowed_origin_gets_no_cors_headers(self) -> None:
        response = self.client.options(
            "/api/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in response.headers})

    def test_localhost_origin_allowed(self) -> None:
        response = self.client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(
            response.headers.get("access-control-allow-origin"), "http://localhost:5173"
        )

    def test_wildcard_origin_not_configured(self) -> None:
        response = self.client.options(
            "/api/health",
            headers={
                "Origin": "null",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in response.headers})


class TokenStorageTests(_SecurityAuditBase):
    """OAuth token directories are per-account, disjoint, and under the data root."""

    def test_token_dirs_are_per_account(self) -> None:
        a_id, b_id = self._ids()
        a_dir = self.settings.for_account(a_id).oauth_token_dir.resolve()
        b_dir = self.settings.for_account(b_id).oauth_token_dir.resolve()
        root = self.temp_dir.name
        self.assertTrue(str(a_dir).startswith(str(Path(root).resolve())))
        self.assertTrue(str(b_dir).startswith(str(Path(root).resolve())))
        self.assertNotEqual(a_dir, b_dir)
        self.assertIn("oauth_tokens", a_dir.parts)
        self.assertTrue(a_dir.is_dir())
        self.assertTrue(b_dir.is_dir())

    def test_protected_app_password_round_trips(self) -> None:
        from backend.storage.secret_vault import protect_secret, reveal_secret

        key_dir = Path(self.temp_dir.name) / "secret-roundtrip"
        token = protect_secret("abcdefghijklmnop", key_dir)
        self.assertEqual(reveal_secret(token, key_dir), "abcdefghijklmnop")

    def test_no_token_files_exist_after_seed(self) -> None:
        self._ids()
        token_files = [
            p
            for p in Path(self.temp_dir.name).rglob("*.json")
            if "token" in p.name.lower()
        ]
        self.assertEqual(token_files, [])


if __name__ == "__main__":
    unittest.main()
