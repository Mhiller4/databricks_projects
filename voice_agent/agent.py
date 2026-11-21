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
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, cli, function_tool  # noqa: E402
from livekit.plugins import google  # noqa: E402

log = logging.getLogger("care-finder-agent")
API = os.environ.get("CARE_FINDER_API", "http://localhost:8000").rstrip("/")
AGENT_NAME = os.environ.get("AGENT_NAME", "")

# ---------------------------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------------------------

COMMON = """
You are Care Finder, a phone assistant that helps people in India find where to go for a specific kind of care.

USING THE TOOL
- Call find_best_care with the service, the location and the urgency once you have them.
- Location: the more specific the better. Ask for a 6-digit PIN code (repeat it back digit by digit) or a
  locality / neighbourhood with its city ("Bandra, Mumbai"). For a big city, always ask which area.
- Before searching, say the place back to confirm it ("Darbhanga in Bihar, is that right?").
- If the tool result has location_is_precise = false, the distances are from a city or district centre.
  Ask once for the area or PIN code, then search again.
- If the tool says it needs clarification (same name in different places), offer the options it gives,
  then call find_best_care again with the chosen option's query.
- If the tool says the service or place is unknown, say so and ask them to rephrase.
- Tell the caller what the tool's "say" text says, in a natural rhythm. You may smooth the wording, but keep
  every facility name, distance, phone number, confidence level and caution. Never add a fact.

LANGUAGE
- Reply in the language the caller uses (English, Hindi, Bengali, Marathi, Tamil, Telugu and others).
- ALWAYS pass the service and location to the tool in English / Latin letters ("dialysis", "Darbhanga, Bihar",
  "800001"), whatever language the caller speaks.
- When translating the tool's text, keep facility names, phone numbers, distances and confidence levels exact.

SPEAKING STYLE
- Confident and efficient: get to the point, no filler.
- Clear articulation: names, places and numbers said crisply; phone numbers slowly, in groups.
- End each answer with an encouraging wrap-up: one short next step, then ask if they need anything else.

STRICT RULES
- Never name, suggest or describe a hospital, clinic or doctor that did not come from find_best_care.
  Never guess phone numbers, addresses, distances or services. If it isn't in the tool result, say you don't know.
- Answer follow-ups ("why that one?", "anything closer?", "how sure are you?") only from the last tool result.
- You are not a doctor: no diagnosis or medical advice. Always suggest calling the facility before travelling.
- Spoken replies only: no lists, no markdown, no URLs.
""".strip()

GREETER = """
You are Care Finder's greeter. Your only job is to find out who is calling.
Say: "Welcome to Care Finder. If you're a health worker or care provider, press 1 or say provider.
If you're a patient or family member, press 2 or say patient."
- "1", "one", provider, health worker, ASHA, doctor, nurse, NGO, clinic staff -> call set_caller_type("provider").
- "2", "two", patient, family, "my father", "my wife", "for myself" -> call set_caller_type("patient").
- If the caller jumps straight to describing a need, decide from what they said and call set_caller_type.
- If unclear, ask once more. Reply in the caller's language. Do not search for facilities yourself.
""".strip()

PROVIDER = COMMON + """

YOU ARE TALKING TO A HEALTH WORKER OR CARE PROVIDER (community health worker, NGO coordinator, clinic staff).
- Be brisk and professional. Clinical terms are fine (NICU, LSCS, haemodialysis).
- Ask for service, PIN code or locality, and urgency together, in one short question.
- Give all the options the tool returns, with confidence levels and the main caution, and mention the
  closer facility that was skipped and why.
- If asked how we decided: facilities must have direct evidence in their own listing, a trustworthy record,
  and the right facility type; then evidence, trust, clinical depth and distance are weighed. Use the
  how_we_decided numbers from the tool.
- After the results, offer a referral: "Would you like me to read out a referral summary you can note down?"
  If yes, read it slowly from the tool result only: facility name, address, phone, the service, confidence,
  and any caution. Then offer to repeat it.
"""

PATIENT = COMMON + """

YOU ARE TALKING TO A PATIENT OR A FAMILY MEMBER.
- First ask: "Is this an emergency right now?" If it is life-threatening (heavy bleeding, unconscious,
  trouble breathing, severe pain in pregnancy, a bad accident), tell them to call 108 for an ambulance
  immediately, then keep helping.
- Use plain, kind words. No jargon: say "newborn intensive care", not "NICU".
- Then ask what care is needed and where they are: their area or PIN code.
- Give the best option and the one backup the tool's text mentions. Don't list more unless asked.
- Make the next step very clear: call the facility first to check they can see you.
- Be reassuring but never promise availability or treatment.
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
        return {"status": status, "say": resp.get("spoken_summary") or resp.get("message"),
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
        "say": resp["spoken_summary"],
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
        try:
            r = await self.http.post(f"{API}/api/recommend", json={
                "service": service, "location": location, "urgency": urgency, "audience": self.audience,
                "broadcast_to_ui": True, "source": "voice",
            })
            r.raise_for_status()
            out = _compact(r.json())
        except Exception as e:  # never let the model improvise if the backend is down
            log.exception("backend call failed")
            out = {"status": "error", "say": "Sorry, I can't reach the facility database right now. Please try again in a minute.",
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

server = AgentServer()


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
    await session.start(agent=Greeter(), room=ctx.room)


if __name__ == "__main__":
    cli.run_app(server)
