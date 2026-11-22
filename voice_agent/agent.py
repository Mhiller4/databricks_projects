"""Care Finder phone / browser voice agent (LiveKit Agents + Gemini Live).

Call flow
    Greeter   "Press 1 or say 'provider' if you're a health worker; press 2 or say 'patient'..."
              keypad (phone, via SIP DTMF) or voice (browser and phone) -> hands the call to:
    Provider  health workers / NGOs / clinics: concise, clinical, all 3 options, skipped-nearby, verbal referral
    Patient   patients and families: emergency check first (108), plain words, best option + one backup

Grounding rule: no persona ever names a facility on its own. The only data tool is find_best_care, which
calls the deterministic backend (POST /api/recommend). The backend writes the spoken summary for the
caller type; the agent says it naturally and answers follow-ups only from that tool result.

Run (backend must be up on :8000):
    .venv/bin/python agent.py dev        # connects to LiveKit Cloud and waits for calls
    .venv/bin/python agent.py console    # talk to it in this terminal (uses your mic)

Keys come from .env.local (repo root or its parent): LIVEKIT_URL, LIVEKIT_API_KEY,
LIVEKIT_API_SECRET, GOOGLE_API_KEY. Optional: CARE_FINDER_API (default http://localhost:8000),
GEMINI_MODEL, GEMINI_VOICE, AGENT_NAME (blank = join every new room; set it for explicit dispatch).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
for p in (HERE / ".env.local", HERE.parent / ".env.local", HERE.parent.parent / ".env.local"):
    if p.exists():
        load_dotenv(p, override=False)

from livekit import rtc  # noqa: E402
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, cli, function_tool, get_job_context  # noqa: E402
from livekit.plugins import google  # noqa: E402

log = logging.getLogger("care-finder-agent")
# Inside the Databricks App the backend runs in the same container on DATABRICKS_APP_PORT.
API = os.environ.get("CARE_FINDER_API", f"http://127.0.0.1:{os.environ.get('DATABRICKS_APP_PORT', '8000')}").rstrip("/")
AGENT_NAME = os.environ.get("AGENT_NAME", "")
RESULT_TOPIC = "care-finder.result"  # full /api/recommend payloads for the web page
ROLE_ATTRIBUTE = "care_finder.role"  # set by the web page token (POST /api/livekit/token)

# ---------------------------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------------------------

COMMON = """
You are Care Finder, a phone assistant that helps people in India work out where to go for a specific kind of care.
You sound like a calm, kind person on a health helpline: warm, unhurried, plain spoken.

HOW A CONVERSATION GOES
1. Find out what care is needed and where the patient is. A 6-digit PIN code or an area with its city
   ("Bandra, Mumbai") works best. For a big city, ask which area. Say the place back to confirm it
   ("Darbhanga in Bihar, is that right?"). Read a PIN back digit by digit.
2. Call find_best_care.
3. Give the short answer: tell the caller what the tool's "answer" text says, in your own natural rhythm.
   That's where to go, one alternative, and how sure you are. Stop there. Don't add the reasons,
   the evidence or the other options yet.
4. Then ask, briefly and naturally, if there's anything else you can help with. Vary the wording, for example
   "Is there anything else I can help with?" or "Would you like their number, or anything else?"
5. Only when they ask for more, give more:
   - "Why?", "How do you know?", "Are you sure?", "Tell me more about it" -> say the tool's "why" text.
     That's the full picture: what their listing says, how many sources, cautions, how you narrowed it down,
     the closer place you passed over, and their number.
   - "Anything else?", "Other options?", "Is there anything closer?" -> say the tool's "more" text.
   - "What's their number?" -> read the phone number of the place they mean, slowly, in groups.
   - "Where exactly is it?" -> read that place's address.
   After each of these, check again if there's anything else.
6. If the tool says the place needs clarifying (the same name in different areas), offer the options it gives
   and search again with the one they pick. If the service or place is unknown, say so and ask them to rephrase.
   If location_is_precise is false and they haven't given an area yet, the answer already asks for one;
   search again when they tell you.

LANGUAGE
- Reply in the caller's language (English, Hindi, Bengali, Marathi, Tamil, Telugu and others).
- Always pass the service and the place to the tool in English letters ("dialysis", "Darbhanga, Bihar",
  "800001"), whatever language the caller speaks.
- When you translate the tool's text, keep names, phone numbers, distances and how sure you are exactly as given.

HOW YOU SPEAK
- Short sentences. One idea at a time. Pause between places.
- Say "my sources say" or "I've seen it mentioned", never "the database" or "the record".
- Say names, places and numbers clearly, and phone numbers slowly.
- No filler, no lists, no markdown, no URLs.

RULES YOU NEVER BREAK
- Only mention hospitals, clinics or doctors that came from find_best_care. Never guess a phone number,
  address, distance or service. If it isn't in the tool result, say you don't know.
- Answer follow-up questions only from the last tool result.
- You're not a doctor. Don't diagnose or give medical advice. Suggest calling the place before travelling.
""".strip()

GREETER = """
You are Care Finder's greeter. Your only job is to find out who is calling.
Say: "Welcome to Care Finder. If you're a health worker or care provider, press 1 or say provider.
If you're a patient or family member, press 2 or say patient."
- "1", "one", provider, health worker, ASHA, doctor, nurse, NGO, clinic staff -> call set_caller_type("provider").
- "2", "two", patient, family, "my father", "my wife", "for myself" -> call set_caller_type("patient").
- If the caller jumps straight to describing a need, decide from what they said and call set_caller_type.
- If unclear, ask once more. Reply in the caller's language. Don't search for facilities yourself.
""".strip()

PROVIDER = COMMON + """

YOU'RE TALKING TO A HEALTH WORKER OR CARE PROVIDER (community health worker, NGO coordinator, clinic staff).
- Be brisk and professional. Clinical terms are fine (NICU, LSCS, haemodialysis).
- Ask for the service, the PIN code or area, and whether it's urgent, in one short question.
- If they want a referral to note down, read it slowly from the tool result: the place's name, address,
  phone number, the service and how sure you are. Offer to repeat it.
"""

PATIENT = COMMON + """

YOU'RE TALKING TO A PATIENT OR A FAMILY MEMBER.
- First ask if this is an emergency right now. If it's life-threatening (heavy bleeding, unconscious,
  trouble breathing, severe pain in pregnancy, a bad accident), tell them to call 108 for an ambulance
  straight away, then keep helping.
- Use plain, kind words. Say "newborn intensive care", not "NICU".
- Make the next step clear: call the place first to check they can see you.
- Be reassuring, but never promise that a place has a bed or will treat them.
"""

PERSONA_INTRO = {
    "provider": "Briefly confirm you'll help them find a facility, then ask in one sentence for the service, "
                "the patient's PIN code or locality, and whether it's an emergency.",
    "patient": "Say in one short sentence that you're here to help them find care, then ask whether this is an "
               "emergency right now.",
}


# ---------------------------------------------------------------------------------------------
# Tool output for the LLM
# ---------------------------------------------------------------------------------------------


def _compact(resp: dict) -> dict:
    """What the LLM gets back: the spoken text plus only the facts it may use for follow-ups."""
    status = resp.get("status")
    if status != "ok":
        return {"status": status, "answer": resp.get("spoken_summary") or resp.get("message"),
                "options": [o.get("query", o) if isinstance(o, dict) else o for o in resp.get("options", [])][:6]}

    def fac(r: dict) -> dict:
        return {
            "tier": r.get("tier_label"), "name": r["name"], "type": r.get("facility_type"),
            "address": r.get("address"), "city": r.get("city"), "district": r.get("district"), "state": r.get("state"),
            "distance_km": r["distance_km"], "confidence": r["confidence"], "phone": r.get("phone"),
            "why": r.get("why", [])[:3], "cautions": r.get("cautions", [])[:3],
            "evidence_quotes": [f"{c['field']}: {c['text']}" for c in r.get("citations", [])[:2]],
        }

    loc = resp["query"]["location"]
    return {
        "status": "ok",
        "answer": (resp.get("spoken") or {}).get("answer", resp["spoken_summary"]),
        "why": (resp.get("spoken") or {}).get("why"),
        "more": (resp.get("spoken") or {}).get("more"),
        "location_used": loc["display_name"],
        "location_is_precise": loc.get("is_precise", True),
        "service": resp["query"]["service"]["label"],
        "recommendations": [fac(r) for r in resp.get("recommendations") or resp.get("nearest_beyond_radius") or []],
        "care_desert": resp["medical_desert_alert"].get("message"),
        "skipped_nearby": [{"name": s["name"], "distance_km": s["distance_km"], "why_not": s["reasons"][0]}
                           for s in resp.get("skipped_nearby", [])[:3]],
        "how_we_decided": f"{resp['funnel'][4]['count']} facilities nearby mention this service; "
                          f"{resp['funnel'][5]['count']} have direct evidence; {resp['funnel'][6]['count']} passed every check.",
    }


# ---------------------------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------------------------


class CareAgent(Agent):
    """A persona with the one grounded data tool."""

    audience = ""

    def __init__(self, instructions: str, chat_ctx=None) -> None:
        super().__init__(instructions=instructions, chat_ctx=chat_ctx)
        self.http = httpx.AsyncClient(timeout=15)

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions=PERSONA_INTRO[self.audience])

    @function_tool()
    async def find_best_care(self, context: RunContext, service: str, location: str, urgency: str = "routine") -> str:
        """Find the best verified facilities for a medical service near a location in India.

        Args:
            service: The care needed, in English, e.g. "dialysis", "emergency c-section", "NICU", "MRI".
            location: A 6-digit PIN code, a locality with its city ("Bandra, Mumbai"), a town, a district, or
                "town, state", in English letters.
            urgency: "emergency" if the patient needs care right now, otherwise "routine".
        """
        urgency = "emergency" if str(urgency).lower().startswith("emerg") else "routine"
        log.info("find_best_care audience=%s service=%r location=%r urgency=%s", self.audience, service, location, urgency)
        room = get_job_context().room
        try:
            r = await self.http.post(f"{API}/api/recommend", json={
                "service": service, "location": location, "urgency": urgency, "audience": self.audience,
                "broadcast_to_ui": True, "source": "voice", "session": room.name,
            })
            r.raise_for_status()
            full = r.json()
            out = _compact(full)
            try:  # the web page in this room renders the full result (map, cards, funnel); design §5
                await room.local_participant.send_text(json.dumps(full, ensure_ascii=False, default=str), topic=RESULT_TOPIC)
            except Exception:
                log.warning("could not publish result to the room", exc_info=True)
        except Exception as e:  # never let the model improvise if the backend is down
            log.exception("backend call failed")
            out = {"status": "error", "answer": "Sorry, I can't look that up right now. Could you try again in a minute?",
                   "detail": str(e)[:200]}
        return json.dumps(out, ensure_ascii=False)


class ProviderAgent(CareAgent):
    audience = "provider"

    def __init__(self, chat_ctx=None) -> None:
        super().__init__(PROVIDER, chat_ctx)


class PatientAgent(CareAgent):
    audience = "patient"

    def __init__(self, chat_ctx=None) -> None:
        super().__init__(PATIENT, chat_ctx)


PERSONAS = {"provider": ProviderAgent, "patient": PatientAgent, "1": ProviderAgent, "2": PatientAgent}


class Greeter(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=GREETER)

    async def on_enter(self) -> None:
        self.session.generate_reply(instructions="Greet the caller and give the two options, exactly as in your instructions.")

    @function_tool()
    async def set_caller_type(self, context: RunContext, caller_type: str) -> Agent:
        """Hand the call to the right assistant once you know who is calling.

        Args:
            caller_type: "provider" for health workers and care providers, "patient" for patients and family.
        """
        cls = PatientAgent if str(caller_type).lower().startswith(("pat", "fam", "2")) else ProviderAgent
        log.info("caller type (voice): %s", cls.audience)
        return cls(chat_ctx=self.chat_ctx)


# ---------------------------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------------------------

# The worker's own health server must not take the app port (design §4).
server = AgentServer(port=int(os.environ.get("LIVEKIT_AGENT_PORT", "8091")))


@server.rtc_session(agent_name=AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            model=os.environ.get("GEMINI_MODEL") or "gemini-3.8-live",  # Fola is only available on 3.8 (checked Nov 21)
            voice=os.environ.get("GEMINI_VOICE", "Fola"),
            temperature=0.4,
            # Without an explicit version the Live WebSocket endpoint returns 404 (checked Nov 21).
            api_version=os.environ.get("GEMINI_API_VERSION", "v1beta"),
        ),
    )

    def on_dtmf(ev: rtc.SipDTMF) -> None:
        """Phone keypad: 1 = provider, 2 = patient (only while the greeter is active)."""
        cls = PERSONAS.get(ev.digit)
        if cls and isinstance(session.current_agent, Greeter):
            log.info("caller type (keypad %s): %s", ev.digit, cls.audience)
            session.interrupt()
            session.update_agent(cls(chat_ctx=session.current_agent.chat_ctx))

    ctx.room.on("sip_dtmf_received", on_dtmf)
    # Web users pick their role on the page; it arrives as a participant attribute, so skip the greeter.
    participant = await ctx.wait_for_participant()
    role = (participant.attributes or {}).get(ROLE_ATTRIBUTE, "")
    first = PERSONAS[role]() if role in ("provider", "patient") else Greeter()
    log.info("session start: room=%s role=%s", ctx.room.name, role or "(greeter)")
    await session.start(agent=first, room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
