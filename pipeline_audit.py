"""Pipeline audit: boot the app fresh, demo-seed, and drive the chat pipeline.

Run with: D:/MLops/.venv/Scripts/python.exe pipeline_audit.py
Ollama is NOT running; heuristic intent parsing and the fallback drafter are
exercised. All JSON evidence is printed with STEP markers.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.automation import Contact
from backend.automation.contact_resolver import ContactResolver
from backend.automation.dispatcher import Dispatcher
from backend.config import Settings
from backend.main import create_app
from backend.schemas import DispatchRequest


def step(title: str, payload) -> None:
    print(f"\n===== STEP: {title} =====")
    print(json.dumps(payload, indent=2, default=str)[:2600])


def main() -> None:
    temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    settings = Settings(
        local_user_data_dir=Path(temp_dir.name),
        profiler_mode="heuristic",
        model_name="not-installed-for-test",
    )
    app = create_app(settings=settings)
    client = TestClient(app)

    # --- Boot + demo seed ---------------------------------------------------
    response = client.post("/api/onboarding/demo-seed")
    assert response.status_code == 200, response.text
    accounts = {
        a["email"]: a for a in client.get("/api/accounts").json()["accounts"]
    }
    sam_id = accounts["sam@cloudscale.io"]["account_id"]
    step("demo-seed + accounts", {"sam_id": sam_id, "emails": sorted(accounts)})

    # --- Build sam's profile (heuristic profiler, offline) -------------------
    built = client.post("/api/onboarding/build-profile", headers={"X-Account-ID": sam_id})
    assert built.status_code == 200, built.text
    step("build-profile (sam)", {
        "profile_id": built.json()["profile_id"],
        "formality": built.json()["global_style_card"]["formality"],
    })

    # --- Seed sam's @cloudscale.io contacts ---------------------------------
    resolver = ContactResolver(settings.for_account(sam_id).contacts_path)
    for contact in [
        Contact(email="manu@cloudscale.io", full_name="Manu Rao",
                first_name="Manu", last_name="Rao", company_domain="cloudscale.io"),
        Contact(email="jatin@cloudscale.io", full_name="Jatin Kumar",
                first_name="Jatin", last_name="Kumar", company_domain="cloudscale.io"),
        Contact(email="chiranth@cloudscale.io", full_name="Chiranth Bhat",
                first_name="Chiranth", last_name="Bhat", company_domain="cloudscale.io"),
    ]:
        resolver.upsert_contact(contact)
    step("seeded sam contacts", [c.email for c in resolver.list_contacts()])

    headers = {"X-Account-ID": sam_id}

    # --- Turn 1: to + cc resolution, draft produced --------------------------
    turn1 = client.post(
        "/api/chat/turn",
        headers=headers,
        json={
            "user_message": (
                "send an email to manu with cc attached to jatin and chiranth "
                "about postponing tomorrow's sprint review"
            ),
            "session_id": "audit-sprint-review",
        },
    )
    assert turn1.status_code == 200, turn1.text
    t1 = turn1.json()
    step("turn1 to/cc resolution + draft", {
        "status": t1["status"],
        "parsed": t1["parsed"],
        "to": [r["matched_email"] for r in t1["resolutions"]["to"]],
        "cc": [r["matched_email"] for r in t1["resolutions"]["cc"]],
        "review_reason": t1["review_reason"],
        "draft_card": {
            "to": t1["draft_card"]["to"],
            "cc": t1["draft_card"]["cc"],
            "subject": t1["draft_card"]["subject"],
            "status": t1["draft_card"]["status"],
            "body_head": (t1["draft_card"]["body"] or "")[:160],
        },
    })
    assert t1["resolutions"]["to"][0]["matched_email"] == "manu@cloudscale.io"
    cc_emails = [r["matched_email"] for r in t1["resolutions"]["cc"]]
    assert cc_emails == ["jatin@cloudscale.io", "chiranth@cloudscale.io"], cc_emails
    assert t1["draft_card"]["body"], "draft body must be produced"

    # --- Turn 2: unknown name -> NEEDS_CLARIFICATION -------------------------
    turn2 = client.post(
        "/api/chat/turn",
        headers=headers,
        json={"user_message": "email zoltan about x", "session_id": "audit-zoltan"},
    )
    assert turn2.status_code == 200, turn2.text
    t2 = turn2.json()
    step("turn2 unknown recipient", {
        "status": t2["status"],
        "assistant_message": t2["assistant_message"],
        "to_resolution": t2["resolutions"]["to"],
    })
    assert t2["status"] == "NEEDS_CLARIFICATION"
    # Offline heuristics cannot catch an unknown lowercase name as a candidate
    # (no LLM extraction), so the turn falls into the generic no-recipient
    # clarification. Either shape is a safe ask-for-clarification outcome.
    if t2["resolutions"]["to"]:
        assert t2["resolutions"]["to"][0]["status"] == "NEEDS_CLARIFICATION"

    # --- Turn 3: never-emailed address -> first-recipient gate ---------------
    turn3 = client.post(
        "/api/chat/turn",
        headers=headers,
        json={
            "user_message": "send an email to manu about the delay",
            "session_id": "audit-gate",
            "auto_send": True,  # gate must still hold the draft
        },
    )
    assert turn3.status_code == 200, turn3.text
    t3 = turn3.json()
    step("turn3 first-recipient gate (auto_send=True)", {
        "status": t3["status"],
        "review_reason": t3["review_reason"],
        "draft_card_status": t3["draft_card"]["status"],
        "card_id": t3["draft_card"]["card_id"],
        "draft_id_on_card": t3["draft_card"]["draft_id"],
    })
    assert t3["status"] == "PENDING_REVIEW"
    assert "first contact" in (t3["review_reason"] or "")

    # --- Approve-and-learn with the chat-turn draft card ---------------------
    card_id = t3["draft_card"]["card_id"]
    approve1 = client.post(
        "/api/email/approve-and-learn",
        headers=headers,
        json={
            "draft_id": card_id,
            "final_subject": "Postponing tomorrow's sprint review",
            "final_body": "Hi Manu,\n\nMoving the sprint review to Friday.\n\nBest",
        },
    )
    assert approve1.status_code == 200, approve1.text
    step("approve-and-learn (chat-turn card id)", approve1.json())
    assert isinstance(approve1.json()["extracted_rules"], list)

    # --- Approve-and-learn SENT path (pending draft staged by the app's own
    #     dispatcher helper, because offline dispatch cannot save one) ---------
    original_cwd = os.getcwd()
    os.chdir(temp_dir.name)  # demo outbox must not pollute the repo
    try:
        a_settings = settings.for_account(sam_id)
        Dispatcher(a_settings)._save_pending_draft(
            draft_id="audit-draft-1",
            request=DispatchRequest(
                provider="demo",
                to=["manu@cloudscale.io"],
                subject="Postponing tomorrow's sprint review",
                intent_bullets="- postpone sprint review",
                auto_send=False,
            ),
            draft="Hi Manu,\n\nMoving the sprint review to Friday.\n\nBest",
            profile_id="audit-profile",
            recipient_profiles={},
        )
        approve2 = client.post(
            "/api/email/approve-and-learn",
            headers=headers,
            json={
                "draft_id": "audit-draft-1",
                "final_subject": "Postponing tomorrow's sprint review",
                "final_body": "Hi Manu,\n\nMoving the sprint review to Friday - does that work?\n\nBest",
            },
        )
        assert approve2.status_code == 200, approve2.text
        step("approve-and-learn (dispatch-shaped pending draft)", approve2.json())
        outbox = Path("local_user_data/demo_outbox.jsonl")
        step("demo outbox after approval",
             [json.loads(line)["to"] for line in outbox.read_text().splitlines()] if outbox.exists() else [])
    finally:
        os.chdir(original_cwd)

    print("\nPIPELINE AUDIT COMPLETE")


if __name__ == "__main__":
    main()
