import re
from datetime import datetime


class OfflineMedicalAI:
    """
    Zero-dependency, offline Clinical Intelligence & Symptom Triage Engine.
    Operates 100% locally with patient profile context awareness.
    """

    def __init__(self):
        self.disclaimer = (
            "⚠️ Disclaimer: I am an automated health assistant for informational triage. "
            "In life-threatening situations, call emergency services or visit the nearest hospital."
        )

    def analyze(self, query: str, patient_profile: dict = None) -> dict:
        """
        Analyze user health query considering the patient's personal medical profile.
        Returns a structured dictionary with response, triage_level, and suggestions.
        """
        q = query.lower().strip()
        patient_name = patient_profile.get("full_name", "Patient") if patient_profile else "Patient"
        patient_allergies = patient_profile.get("allergies", "").lower() if patient_profile else ""
        patient_conditions = patient_profile.get("existing_conditions", "").lower() if patient_profile else ""
        patient_meds = patient_profile.get("current_medications", "").lower() if patient_profile else ""
        emergency_contact = patient_profile.get("emergency_name", "Emergency Contact") if patient_profile else "Emergency Contact"
        emergency_phone = patient_profile.get("emergency_number", "") if patient_profile else ""

        # ---------------- 1. EMERGENCY RED FLAGS ----------------
        emergencies = [
            ("chest pain", "Severe chest pressure or pain can indicate myocardial infarction (heart attack)."),
            ("shortness of breath", "Sudden acute breathlessness is a medical emergency."),
            ("can't breathe", "Acute respiratory distress requires immediate airway management."),
            ("stroke", "Symptoms of stroke (Face drooping, Arm weakness, Speech difficulty - FAST)."),
            ("unconscious", "Loss of consciousness requires immediate 911/emergency intervention."),
            ("heavy bleeding", "Uncontrolled bleeding requires immediate pressure and trauma care."),
            ("poison", "Suspected poisoning requires immediate poison control center contact.")
        ]

        for trigger, desc in emergencies:
            if trigger in q:
                alert_text = (
                    f"🚨 **CRITICAL MEDICAL EMERGENCY DETECTED**\n\n"
                    f"{desc}\n\n"
                    f"**Immediate Actions Required:**\n"
                    f"1. Call local emergency services (112 / 911 / 108) immediately.\n"
                    f"2. Notify your emergency contact: **{emergency_contact}** ({emergency_phone}).\n"
                    f"3. Do not drive yourself; remain calm and seated until paramedic arrival."
                )
                return {
                    "reply": alert_text,
                    "level": "emergency",
                    "suggestions": ["Call Emergency Services", "Notify Emergency Contact", "First Aid for Heart Attack"]
                }

        # ---------------- 2. PATIENT PROFILE ALLERGY CHECK ----------------
        med_keywords = [
            "penicillin", "amoxicillin", "aspirin", "ibuprofen", "peanuts", "peanut",
            "paracetamol", "sulfa", "codeine", "lactose", "dairy", "milk",
            "shellfish", "gluten", "eggs", "soy", "morphine"
        ]
        found_warnings = []

        for med in med_keywords:
            if med in q and med in patient_allergies:
                found_warnings.append(
                    f"⚠️ **CONTRAINDICATION ALERT**: Your medical profile registers a known allergy to **{med.capitalize()}**.\n"
                    f"Do NOT consume medications containing {med}."
                )

        if found_warnings:
            return {
                "reply": "\n\n".join(found_warnings) + "\n\nPlease consult your prescribing physician for a hypoallergenic alternative.",
                "level": "warning",
                "suggestions": ["View My Health Profile", "Safe Medication Alternatives", "Contact Doctor"]
            }

        # General medication guidance if queried
        if "penicillin" in q or "amoxicillin" in q:
            return {
                "reply": (
                    "💊 **Penicillin / Beta-Lactam Antibiotic Information**:\n\n"
                    "• **Use**: Prescribed exclusively for bacterial infections (strep throat, bacterial pneumonia, skin infections). It is ineffective against viral colds or flu.\n"
                    "• **Important**: Always complete the full prescribed antibiotic course even if feeling better.\n"
                    "• **Hypersensitivity Warning**: Watch for rash, hives, or swelling. Discontinue immediately if allergic symptoms appear."
                ),
                "level": "info",
                "suggestions": ["Check Allergy Contraindications", "When to Stop Antibiotics", "Doctor Consultation"]
            }

        # ---------------- 3. ASTHMA & RESPIRATORY ----------------
        if "asthma" in q or "inhaler" in q or "wheezing" in q:
            reply = (
                f"🫁 **Asthma Management Protocol**:\n\n"
                f"• **Immediate Action**: Sit upright. Use your fast-acting reliever inhaler (e.g., Salbutamol 2 puffs, wait 1 minute, repeat if necessary).\n"
                f"• **Triggers to Avoid**: Dust mites, cold air, smoke, strong fragrances, pollen.\n"
                f"• **When to Seek Urgent Care**: Inhaler provides no relief within 15 minutes, blue fingernails or lips, inability to speak full sentences."
            )
            if "asthma" in patient_conditions:
                reply = f"*(Note: Noted in your profile as an active condition)*\n\n" + reply
            return {
                "reply": reply,
                "level": "info",
                "suggestions": ["How to use an Inhaler", "Asthma Triggers Checklist", "Emergency Red Flags"]
            }

        # ---------------- 4. DIABETES & BLOOD SUGAR ----------------
        if any(w in q for w in ["diabetes", "sugar", "glucose", "insulin", "hba1c"]):
            reply = (
                f"🩸 **Diabetes Care & Monitoring Guidelines**:\n\n"
                f"• **Target Blood Sugar (General Adult)**:\n"
                f"   - Fasting: 80 - 130 mg/dL\n"
                f"   - Post-meal (2 hrs): < 180 mg/dL\n"
                f"   - Target HbA1c: Typically < 7.0%\n\n"
                f"• **Hypoglycemia (Low Sugar < 70 mg/dL)**:\n"
                f"   Apply the **15-15 Rule**: Consume 15g fast-acting carbohydrates (half cup juice or 3 glucose tablets), wait 15 mins, re-test.\n\n"
                f"• **Dietary Principles**: Favor high-fiber complex carbs (whole grains, legumes) and lean proteins. Avoid refined sodas and sweets."
            )
            if "diabetes" in patient_conditions:
                reply = f"*(Tailored for your profile: Diabetes management)*\n\n" + reply
            return {
                "reply": reply,
                "level": "info",
                "suggestions": ["Symptoms of Low Blood Sugar", "Diabetes Meal Plan", "HbA1c Test Frequency"]
            }

        # ---------------- 5. BLOOD PRESSURE & HYPERTENSION ----------------
        if any(w in q for w in ["blood pressure", "hypertension", "bp"]):
            reply = (
                f"❤️ **Blood Pressure Categories (AHA Standards)**:\n\n"
                f"• **Normal**: Systolic < 120 and Diastolic < 80 mmHg\n"
                f"• **Elevated**: 120-129 and < 80 mmHg\n"
                f"• **Stage 1 Hypertension**: 130-139 or 80-89 mmHg\n"
                f"• **Stage 2 Hypertension**: ≥ 140 or ≥ 90 mmHg\n"
                f"• **Hypertensive Crisis**: > 180 and/or > 120 mmHg (Seek emergency care immediately).\n\n"
                f"**Lifestyle tips**: Reduce sodium intake (< 2,300mg/day), practice 30 mins brisk walking daily, reduce stress."
            )
            return {
                "reply": reply,
                "level": "info",
                "suggestions": ["How to Measure BP Correctly", "Low Sodium Diet Tips", "Hypertensive Crisis Symptoms"]
            }

        # ---------------- 6. FEVER, COLD & VIRAL SYMPTOMS ----------------
        if any(w in q for w in ["fever", "temperature", "cold", "flu", "cough"]):
            reply = (
                f"🌡️ **Fever & Viral Care Protocol**:\n\n"
                f"• **Rest & Hydration**: Drink plenty of water, electrolytes, and warm soups.\n"
                f"• **Temperature Control**: Tepid sponging on forehead; dress in breathable clothing.\n"
                f"• **Medication**: Antipyretics like Paracetamol (unless contraindicated or liver conditions exist). Always check pediatric dosage by weight.\n"
                f"• **Red Flags**: Fever > 103°F (39.4°C), stiff neck, confusion, breathing difficulties, or fever lasting longer than 3 days requires clinical review."
            )
            return {
                "reply": reply,
                "level": "info",
                "suggestions": ["When is a Fever Dangerous?", "Home Remedies for Cold", "Hydration Checklist"]
            }

        # ---------------- 7. HEADACHE & MIGRAINE ----------------
        if "headache" in q or "migraine" in q:
            reply = (
                f"🧠 **Headache Analysis & Self-Care**:\n\n"
                f"• **Tension Headache**: Mild to moderate band-like pressure. Rest in a dark, quiet room, apply cold/warm compress, stay hydrated.\n"
                f"• **Migraine**: Throbbing, usually one-sided, sensitivity to light/sound. Rest and prescribe acute migraine medications if diagnosed.\n"
                f"• **🚨 Warning Signs (SNOOP criteria)**: Sudden 'thunderclap' onset, accompanied by fever, stiff neck, neurological deficits (numbness, weakness) requires immediate ER evaluation."
            )
            return {
                "reply": reply,
                "level": "info",
                "suggestions": ["Thunderclap Headache Signs", "Migraine Triggers", "Hydration & Eye Strain"]
            }

        # ---------------- 8. FIRST AID (BURNS, CUTS, CHOKING) ----------------
        if "burn" in q:
            reply = (
                f"🩹 **First Aid for Thermal Burns**:\n\n"
                f"1. **Cool the Burn**: Run cool (not icy) tap water over the burn for 10 to 20 minutes.\n"
                f"2. **Do Not Apply Ice, Butter, or Toothpaste**: These damage fragile tissue.\n"
                f"3. **Cover**: Use sterile, non-adherent dressing or clean cling film.\n"
                f"4. **Seek Medical Care If**: Burn is larger than patient's palm, on face/hands/joints, or blistering deeply."
            )
            return {
                "reply": reply,
                "level": "info",
                "suggestions": ["First Aid for Cuts", "Chemical Burns", "Emergency Contacts"]
            }

        if "cpr" in q or "heart stop" in q:
            reply = (
                f"🫀 **Hands-Only CPR Protocol (Adult)**:\n\n"
                f"1. Call Emergency Services immediately.\n"
                f"2. Place hands in the center of the chest.\n"
                f"3. Push hard and fast at a rate of 100-120 beats per minute (to the rhythm of 'Stayin' Alive').\n"
                f"4. Allow complete chest recoil between compressions.\n"
                f"5. Continue until automated external defibrillator (AED) arrives or medical personnel take over."
            )
            return {
                "reply": reply,
                "level": "emergency",
                "suggestions": ["Find Nearest Defibrillator", "Choking / Heimlich Maneuver", "Call 112/911"]
            }

        # ---------------- 9. PROFILE SUMMARY & OVERVIEW ----------------
        if any(w in q for w in ["my profile", "my health", "who am i", "my conditions", "my allergies"]):
            reply = (
                f"👤 **Medical Profile Summary for {patient_name}**:\n\n"
                f"• **Blood Group**: {patient_profile.get('blood_group', 'Not specified')}\n"
                f"• **Age / Gender**: {patient_profile.get('age', '--')} yrs • {patient_profile.get('gender', 'N/A')}\n"
                f"• **Known Allergies**: {patient_profile.get('allergies', 'None reported')}\n"
                f"• **Chronic Conditions**: {patient_profile.get('existing_conditions', 'None reported')}\n"
                f"• **Current Medications**: {patient_profile.get('current_medications', 'None reported')}\n"
                f"• **Emergency Contact**: {emergency_contact} ({emergency_phone})\n\n"
                f"Your QR code is active and encodes this vital emergency information."
            )
            return {
                "reply": reply,
                "level": "profile",
                "suggestions": ["Update My Profile", "Download Emergency QR Code", "View Family Medical History"]
            }

        # ---------------- 10. GENERAL CONVERSATIONAL / HEALTH TIPS ----------------
        if any(w in q for w in ["hello", "hi", "hey", "who are you", "help"]):
            reply = (
                f"Hello {patient_name}! 👋 I am your **Medicare Offline AI Health Assistant**.\n\n"
                f"I can assist you with:\n"
                f"• Checking your personal health profile & allergy contraindications\n"
                f"• Evaluating common symptoms (fever, headache, cough, etc.)\n"
                f"• Guidance on chronic conditions (Diabetes, Blood Pressure, Asthma)\n"
                f"• Step-by-step first aid protocols\n\n"
                f"How can I help you today?"
            )
            return {
                "reply": reply,
                "level": "greeting",
                "suggestions": ["Check My Allergy Contraindications", "Asthma Inhaler Guide", "Diabetes Diet Advice", "First Aid for Burns"]
            }

        # Default intelligent response
        return {
            "reply": (
                f"Thank you for your question regarding '{query}'.\n\n"
                f"Based on clinical general knowledge, self-care for non-urgent symptoms includes adequate rest, hydration, "
                f"and monitoring symptom progression.\n\n"
                f"If you are experiencing persistent, severe, or worsening discomfort, please consult your physician or schedule a clinic visit.\n\n"
                f"{self.disclaimer}"
            ),
            "level": "general",
            "suggestions": ["Check My Profile", "First Aid Guide", "Emergency Red Flags", "Contact Clinic"]
        }


# Singleton instance
ai_assistant = OfflineMedicalAI()
