"""Approved, fixed guidance the voice agent may give (the "light guidance" policy).

Everything here is written by the team and reviewed. The agent reads it through the get_guidance tool and may
translate it, but must not add to it. Nothing here is medical advice: no diagnosis, no treatment, no medicines,
no judgement about whether someone needs a service. Facility facts never come from here; only find_best_care
gives those.
"""

from __future__ import annotations

EMERGENCY_NUMBERS = (
    "For an ambulance in an emergency, call 108. It's free. "
    "For a pregnant woman or a sick newborn, 102 is the free transport line in most states. "
    "112 is the national emergency number for police, fire and ambulance."
)

WHAT_TO_BRING = (
    "Take a photo ID, any previous reports, scans or discharge papers, the list of medicines the patient takes, "
    "and an Ayushman Bharat card or insurance card if you have one."
)

COST_AND_INSURANCE = (
    "I don't have prices, bed availability or insurance details. When you call, ask what it will cost, "
    "whether they have space today, and whether they accept the Ayushman Bharat card or your insurance."
)

GENERAL_QUESTIONS = "Ask if they can see the patient today, whether you need an appointment, and what it will cost."

# service_key -> (what it is, in plain words; what to ask when calling)
SERVICES: dict[str, tuple[str, str]] = {
    "dialysis": (
        "Dialysis is when a machine cleans the blood because the kidneys can't do it well enough.",
        "Ask if they have a dialysis slot free, how often sessions run, and whether they need the patient's latest blood reports.",
    ),
    "emergency_c_section": (
        "An emergency C-section is an operation to deliver the baby when a normal delivery isn't safe.",
        "Ask if a doctor who does C-sections and an anaesthetist are there right now, and whether they have blood available.",
    ),
    "maternity_delivery": (
        "This is a hospital or centre where babies are delivered, with a labour room and trained staff.",
        "Ask if their labour room is open day and night, and whether a doctor or trained midwife is on duty.",
    ),
    "nicu": (
        "A newborn intensive care unit looks after babies who are born early, very small or unwell.",
        "Ask if they have a free newborn intensive care bed today and whether a children's doctor is there.",
    ),
    "icu": (
        "An ICU is intensive care, for patients who need close monitoring or help with breathing.",
        "Ask if they have an ICU bed free right now and whether they have a ventilator if one is needed.",
    ),
    "trauma_care": (
        "Trauma care is emergency treatment for injuries, for example after a road accident or a fall.",
        "Ask if their emergency is open now and whether a surgeon and X-ray or CT are available.",
    ),
    "emergency_department": (
        "A 24-hour emergency department sees urgent cases at any time of day or night.",
        "Ask if the emergency is open right now and if a doctor is on duty.",
    ),
    "burn_care": (
        "A burn unit treats serious burns.",
        "Ask if they have a burn unit or burn ward and a free bed today.",
    ),
    "cardiac_surgery": (
        "Cardiac surgery means heart operations, such as bypass surgery or valve repair.",
        "Ask if their heart surgeon operates there regularly and whether you need a referral or past reports first.",
    ),
    "cardiac_cath": (
        "A cath lab is where doctors open blocked heart arteries, for example with a stent during a heart attack.",
        "Ask if the cath lab works around the clock and if a heart specialist is available now.",
    ),
    "mri": (
        "An MRI is a detailed scan of the inside of the body. It doesn't use X-rays.",
        "Ask when the next MRI slot is, whether you need a doctor's note, and what it costs.",
    ),
    "ct_scan": (
        "A CT scan is a quick, detailed X-ray scan of the inside of the body.",
        "Ask if the CT scanner is working today, whether you need a doctor's note, and what it costs.",
    ),
    "blood_bank": (
        "A blood bank stores blood so patients can be given a transfusion.",
        "Ask if they have the blood group you need, and whether they ask for a donor to replace it.",
    ),
    "chemotherapy": (
        "Chemotherapy is cancer treatment with medicines, usually given in sessions.",
        "Ask if a cancer specialist sees patients there and what reports to bring to the first visit.",
    ),
    "radiotherapy": (
        "Radiotherapy is cancer treatment with targeted radiation.",
        "Ask if their radiotherapy machine is working and how long the waiting list is.",
    ),
    "cataract_surgery": (
        "Cataract surgery replaces the cloudy lens in the eye with a clear one.",
        "Ask how soon they can do the operation and whether there's a free eye camp or a government scheme.",
    ),
}

TOPICS = ("what_is", "what_to_ask", "what_to_bring", "cost_and_insurance", "emergency_numbers")


def guidance(topic: str, service_key: str = "") -> str | None:
    """The approved text for a topic (and service, where it matters), or None if there is none."""
    topic = (topic or "").strip().lower()
    svc = SERVICES.get((service_key or "").strip().lower())
    if topic == "what_is":
        return svc[0] if svc else None
    if topic == "what_to_ask":
        return f"{svc[1]} {GENERAL_QUESTIONS}" if svc else GENERAL_QUESTIONS
    return {"what_to_bring": WHAT_TO_BRING, "cost_and_insurance": COST_AND_INSURANCE,
            "emergency_numbers": EMERGENCY_NUMBERS}.get(topic)
