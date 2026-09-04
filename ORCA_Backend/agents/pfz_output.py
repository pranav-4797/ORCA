"""
User-facing formatting for the official INCOIS / SAMUDRA PFZ finding.

Shared by the Response Agent (LLM path) and the Orchestrator's fast
deterministic path so every official-PFZ answer renders the SAME exact
template regardless of routing depth. Only wordsmithing lives here --
all numbers come directly from the PFZRecommendation the agent produced
(NO fabrication, no LLM in this module).

Only official advisories (DataSource.INCOIS_LIVE) get this template. The
derived/simulated fallbacks keep the existing honest concision.
"""

from __future__ import annotations

OFFICIAL_SOURCE = "Official INCOIS Marine Fisheries (SAMUDRA) live advisory"

# 8-point compass rose with spoken names (225 deg -> "South-West").
_COMPASS = [
    "North", "North-East", "East", "South-East",
    "South", "South-West", "West", "North-West",
]

_VERDICT_BRIEF = {
    "SAFE": "Conditions are favourable for fishing.",
    "CAUTION": "Borderline conditions; proceed carefully.",
    "UNSAFE": "Unsafe conditions; avoid venturing out.",
    "EXTREME": "Severe conditions; do not venture out.",
    "CRITICAL": "Severe conditions; do not venture out.",
}

# Localized labels for the compact PFZ block. Coordinates / numbers stay
# universal; only the fixed scaffolding words are translated so the WHOLE
# answer reads in the user's language. Falls back to English for any missing
# language or key. Proper nouns (INCOIS, SAMUDRA) are kept as-is.
_PFZ_LABELS = {
    "en": {
        "verdict": "VERDICT", "distance": "Distance", "depth": "Depth",
        "source_official": "Official INCOIS (SAMUDRA) live advisory",
        "source_estimated": "Estimated from live sea-surface data — no official INCOIS advisory nearby today",
        "brief": {"SAFE": "favourable for fishing.", "CAUTION": "borderline, proceed carefully.",
                  "UNSAFE": "unsafe, avoid venturing out.", "EXTREME": "severe, do not venture out.",
                  "CRITICAL": "severe, do not venture out."},
    },
    "hi": {
        "verdict": "फैसला", "distance": "दूरी", "depth": "गहराई",
        "source_official": "आधिकारिक INCOIS (SAMUDRA) लाइव सलाह",
        "source_estimated": "लाइव समुद्री सतह डेटा से अनुमानित — आज पास कोई आधिकारिक INCOIS सलाह नहीं",
        "brief": {"SAFE": "मछली पकड़ने के लिए अनुकूल।", "CAUTION": "सीमावर्ती, सावधानी से आगे बढ़ें।",
                  "UNSAFE": "असुरक्षित, समुद्र में न जाएं।", "EXTREME": "गंभीर, समुद्र में न जाएं।",
                  "CRITICAL": "गंभीर, समुद्र में न जाएं।"},
    },
    "mr": {
        "verdict": "निर्णय", "distance": "अंतर", "depth": "खोली",
        "source_official": "अधिकृत INCOIS (SAMUDRA) थेट सल्ला",
        "source_estimated": "थेट समुद्री पृष्ठभाग डेटावरून अंदाजित — आज जवळ अधिकृत INCOIS सल्ला नाही",
        "brief": {"SAFE": "मासेमारीसाठी अनुकूल.", "CAUTION": "सीमारेषेवर, काळजीपूर्वक जा.",
                  "UNSAFE": "असुरक्षित, समुद्रात जाऊ नका.", "EXTREME": "गंभीर, समुद्रात जाऊ नका.",
                  "CRITICAL": "गंभीर, समुद्रात जाऊ नका."},
    },
    "ta": {
        "verdict": "தீர்ப்பு", "distance": "தூரம்", "depth": "ஆழம்",
        "source_official": "அதிகாரப்பூர்வ INCOIS (SAMUDRA) நேரடி ஆலோசனை",
        "source_estimated": "நேரடி கடல் மேற்பரப்பு தரவிலிருந்து மதிப்பிடப்பட்டது — இன்று அருகில் அதிகாரப்பூர்வ INCOIS ஆலோசனை இல்லை",
        "brief": {"SAFE": "மீன்பிடிக்க ஏற்றது.", "CAUTION": "எல்லைநிலை, கவனமாகச் செல்லவும்.",
                  "UNSAFE": "பாதுகாப்பற்றது, கடலுக்குச் செல்ல வேண்டாம்.", "EXTREME": "கடுமையானது, கடலுக்குச் செல்ல வேண்டாம்.",
                  "CRITICAL": "கடுமையானது, கடலுக்குச் செல்ல வேண்டாம்."},
    },
    "te": {
        "verdict": "తీర్పు", "distance": "దూరం", "depth": "లోతు",
        "source_official": "అధికారిక INCOIS (SAMUDRA) ప్రత్యక్ష సలహా",
        "source_estimated": "ప్రత్యక్ష సముద్ర ఉపరితల డేటా నుండి అంచనా — నేడు సమీపంలో అధికారిక INCOIS సలహా లేదు",
        "brief": {"SAFE": "చేపలు పట్టడానికి అనుకూలం.", "CAUTION": "సరిహద్దు, జాగ్రత్తగా వెళ్లండి.",
                  "UNSAFE": "అసురక్షితం, సముద్రంలోకి వెళ్లవద్దు.", "EXTREME": "తీవ్రం, సముద్రంలోకి వెళ్లవద్దు.",
                  "CRITICAL": "తీవ్రం, సముద్రంలోకి వెళ్లవద్దు."},
    },
    "ml": {
        "verdict": "വിധി", "distance": "ദൂരം", "depth": "ആഴം",
        "source_official": "ഔദ്യോഗിക INCOIS (SAMUDRA) തത്സമയ ഉപദേശം",
        "source_estimated": "തത്സമയ കടൽ ഉപരിതല ഡാറ്റയിൽ നിന്ന് കണക്കാക്കിയത് — ഇന്ന് സമീപത്ത് ഔദ്യോഗിക INCOIS ഉപദേശമില്ല",
        "brief": {"SAFE": "മീൻപിടിത്തത്തിന് അനുകൂലം.", "CAUTION": "അതിർത്തി, ശ്രദ്ധയോടെ പോകുക.",
                  "UNSAFE": "സുരക്ഷിതമല്ല, കടലിൽ പോകരുത്.", "EXTREME": "ഗുരുതരം, കടലിൽ പോകരുത്.",
                  "CRITICAL": "ഗുരുതരം, കടലിൽ പോകരുത്."},
    },
    "kn": {
        "verdict": "ತೀರ್ಪು", "distance": "ದೂರ", "depth": "ಆಳ",
        "source_official": "ಅಧಿಕೃತ INCOIS (SAMUDRA) ನೇರ ಸಲಹೆ",
        "source_estimated": "ನೇರ ಸಮುದ್ರ ಮೇಲ್ಮೈ ದತ್ತಾಂಶದಿಂದ ಅಂದಾಜು — ಇಂದು ಹತ್ತಿರ ಅಧಿಕೃತ INCOIS ಸಲಹೆ ಇಲ್ಲ",
        "brief": {"SAFE": "ಮೀನುಗಾರಿಕೆಗೆ ಅನುಕೂಲ.", "CAUTION": "ಗಡಿರೇಖೆ, ಎಚ್ಚರಿಕೆಯಿಂದ ಸಾಗಿ.",
                  "UNSAFE": "ಅಸುರಕ್ಷಿತ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ.", "EXTREME": "ತೀವ್ರ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ.",
                  "CRITICAL": "ತೀವ್ರ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ."},
    },
    "gu": {
        "verdict": "ચુકાદો", "distance": "અંતર", "depth": "ઊંડાઈ",
        "source_official": "અધિકૃત INCOIS (SAMUDRA) લાઇવ સલાહ",
        "source_estimated": "લાઇવ દરિયાઈ સપાટી ડેટા પરથી અંદાજિત — આજે નજીક કોઈ અધિકૃત INCOIS સલાહ નથી",
        "brief": {"SAFE": "માછીમારી માટે અનુકૂળ.", "CAUTION": "સીમારેખા, સાવધાનીથી આગળ વધો.",
                  "UNSAFE": "અસુરક્ષિત, દરિયામાં ન જાઓ.", "EXTREME": "ગંભીર, દરિયામાં ન જાઓ.",
                  "CRITICAL": "ગંભીર, દરિયામાં ન જાઓ."},
    },
    "bn": {
        "verdict": "রায়", "distance": "দূরত্ব", "depth": "গভীরতা",
        "source_official": "সরকারি INCOIS (SAMUDRA) সরাসরি পরামর্শ",
        "source_estimated": "সরাসরি সমুদ্র পৃষ্ঠের ডেটা থেকে অনুমান — আজ কাছে কোনো সরকারি INCOIS পরামর্শ নেই",
        "brief": {"SAFE": "মাছ ধরার জন্য অনুকূল।", "CAUTION": "সীমারেখা, সাবধানে এগিয়ে যান।",
                  "UNSAFE": "অনিরাপদ, সমুদ্রে যাবেন না।", "EXTREME": "গুরুতর, সমুদ্রে যাবেন না।",
                  "CRITICAL": "গুরুতর, সমুদ্রে যাবেন না।"},
    },
    "or": {
        "verdict": "ରାୟ", "distance": "ଦୂରତା", "depth": "ଗଭୀରତା",
        "source_official": "ସରକାରୀ INCOIS (SAMUDRA) ସିଧାସଳଖ ପରାମର୍ଶ",
        "source_estimated": "ସିଧାସଳଖ ସମୁଦ୍ର ପୃଷ୍ଠ ତଥ୍ୟରୁ ଅନୁମାନ — ଆଜି ନିକଟରେ କୌଣସି ସରକାରୀ INCOIS ପରାମର୍ଶ ନାହିଁ",
        "brief": {"SAFE": "ମାଛ ଧରିବା ପାଇଁ ଅନୁକୂଳ।", "CAUTION": "ସୀମାରେଖା, ସାବଧାନରେ ଆଗକୁ ବଢ଼ନ୍ତୁ।",
                  "UNSAFE": "ଅସୁରକ୍ଷିତ, ସମୁଦ୍ରକୁ ଯାଆନ୍ତୁ ନାହିଁ।", "EXTREME": "ଗମ୍ଭୀର, ସମୁଦ୍ରକୁ ଯାଆନ୍ତୁ ନାହିଁ।",
                  "CRITICAL": "ଗମ୍ଭୀର, ସମୁଦ୍ରକୁ ଯାଆନ୍ତୁ ନାହିଁ।"},
    },
    "pa": {
        "verdict": "ਫੈਸਲਾ", "distance": "ਦੂਰੀ", "depth": "ਡੂੰਘਾਈ",
        "source_official": "ਸਰਕਾਰੀ INCOIS (SAMUDRA) ਸਿੱਧੀ ਸਲਾਹ",
        "source_estimated": "ਸਿੱਧੇ ਸਮੁੰਦਰ ਸਤਹਿ ਡੇਟਾ ਤੋਂ ਅਨੁਮਾਨ — ਅੱਜ ਨੇੜੇ ਕੋਈ ਸਰਕਾਰੀ INCOIS ਸਲਾਹ ਨਹੀਂ",
        "brief": {"SAFE": "ਮੱਛੀ ਫੜਨ ਲਈ ਅਨੁਕੂਲ।", "CAUTION": "ਸੀਮਾ-ਰੇਖਾ, ਸਾਵਧਾਨੀ ਨਾਲ ਅੱਗੇ ਵਧੋ।",
                  "UNSAFE": "ਅਸੁਰੱਖਿਅਤ, ਸਮੁੰਦਰ ਵਿੱਚ ਨਾ ਜਾਓ।", "EXTREME": "ਗੰਭੀਰ, ਸਮੁੰਦਰ ਵਿੱਚ ਨਾ ਜਾਓ।",
                  "CRITICAL": "ਗੰਭੀਰ, ਸਮੁੰਦਰ ਵਿੱਚ ਨਾ ਜਾਓ।"},
    },
    # Extra coastal micro-languages — reuse nearest major language so template never falls back to English
    "kok": {
        "verdict": "निर्णय", "distance": "अंतर", "depth": "खोली",
        "source_official": "अधिकृत INCOIS (SAMUDRA) थेट सल्ला",
        "source_estimated": "थेट समुद्री पृष्ठभाग डेटावरून अंदाजित — आज जवळ अधिकृत INCOIS सल्ला नाही",
        "brief": {"SAFE": "मासेमारीसाठी अनुकूल.", "CAUTION": "सीमारेषेवर, काळजीपूर्वक जा.",
                  "UNSAFE": "असुरक्षित, समुद्रात जाऊ नका.", "EXTREME": "गंभीर, समुद्रात जाऊ नका.",
                  "CRITICAL": "गंभीर, समुद्रात जाऊ नका."},
    },
    "tcy": {
        "verdict": "ತೀರ್ಪು", "distance": "ದೂರ", "depth": "ಆಳ",
        "source_official": "ಅಧಿಕೃತ INCOIS (SAMUDRA) ನೇರ ಸಲಹೆ",
        "source_estimated": "ನೇರ ಸಮುದ್ರ ಮೇಲ್ಮೈ ದತ್ತಾಂಶದಿಂದ ಅಂದಾಜು — ಇಂದು ಹತ್ತಿರ ಅಧಿಕೃತ INCOIS ಸಲಹೆ ಇಲ್ಲ",
        "brief": {"SAFE": "ಮೀನುಗಾರಿಕೆಗೆ ಅನುಕೂಲ.", "CAUTION": "ಗಡಿರೇಖೆ, ಎಚ್ಚರಿಕೆಯಿಂದ ಸಾಗಿ.",
                  "UNSAFE": "ಅಸುರಕ್ಷಿತ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ.", "EXTREME": "ತೀವ್ರ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ.",
                  "CRITICAL": "ತೀವ್ರ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ."},
    },
    "kfr": {
        "verdict": "ચુકાદો", "distance": "અંતર", "depth": "ઊંડાઈ",
        "source_official": "અધિકૃત INCOIS (SAMUDRA) લાઇવ સલાહ",
        "source_estimated": "લાઇવ દરિયાઈ સપાટી ડેટા પરથી અંદાજિત — આજે નજીક કોઈ અધિકૃત INCOIS સલાહ નથી",
        "brief": {"SAFE": "માછીમારી માટે અનુકૂળ.", "CAUTION": "સીમારેખા, સાવધાનીથી આગળ વધો.",
                  "UNSAFE": "અસુરક્ષિત, દરિયામાં ન જાઓ.", "EXTREME": "ગંભીર, દરિયામાં ન જાઓ.",
                  "CRITICAL": "ગંભીર, દરિયામાં ન જાઓ."},
    },
    "byr": {
        "verdict": "ತೀರ್ಪು", "distance": "ದೂರ", "depth": "ಆಳ",
        "source_official": "ಅಧಿಕೃತ INCOIS (SAMUDRA) ನೇರ ಸಲಹೆ",
        "source_estimated": "ನೇರ ಸಮುದ್ರ ಮೇಲ್ಮೈ ದತ್ತಾಂಶದಿಂದ ಅಂದಾಜು — ಇಂದು ಹತ್ತಿರ ಅಧಿಕೃತ INCOIS ಸಲಹೆ ಇಲ್ಲ",
        "brief": {"SAFE": "ಮೀನುಗಾರಿಕೆಗೆ ಅನುಕೂಲ.", "CAUTION": "ಗಡಿರೇಖೆ, ಎಚ್ಚರಿಕೆಯಿಂದ ಸಾಗಿ.",
                  "UNSAFE": "ಅಸುರಕ್ಷಿತ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ.", "EXTREME": "ತೀವ್ರ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ.",
                  "CRITICAL": "ತೀವ್ರ, ಸಮುದ್ರಕ್ಕೆ ಹೋಗಬೇಡಿ."},
    },
    "mvv": {
        "verdict": "निर्णय", "distance": "अंतर", "depth": "खोली",
        "source_official": "अधिकृत INCOIS (SAMUDRA) थेट सल्ला",
        "source_estimated": "थेट समुद्री पृष्ठभाग डेटावरून अंदाजित — आज जवळ अधिकृत INCOIS सल्ला नाही",
        "brief": {"SAFE": "मासेमारीसाठी अनुकूल.", "CAUTION": "सीमारेषेवर, काळजीपूर्वक जा.",
                  "UNSAFE": "असुरक्षित, समुद्रात जाऊ नका.", "EXTREME": "गंभीर, समुद्रात जाऊ नका.",
                  "CRITICAL": "गंभीर, समुद्रात जाऊ नका."},
    },
    "ncr": {
        "verdict": "VERDICT", "distance": "Distance", "depth": "Depth",
        "source_official": "Official INCOIS (SAMUDRA) live advisory",
        "source_estimated": "Estimated from live sea-surface data — no official INCOIS advisory nearby today",
        "brief": {"SAFE": "favourable for fishing.", "CAUTION": "borderline, proceed carefully.",
                  "UNSAFE": "unsafe, avoid venturing out.", "EXTREME": "severe, do not venture out.",
                  "CRITICAL": "severe, do not venture out."},
    },
    "adm": {
        "verdict": "VERDICT", "distance": "Distance", "depth": "Depth",
        "source_official": "Official INCOIS (SAMUDRA) live advisory",
        "source_estimated": "Estimated from live sea-surface data — no official INCOIS advisory nearby today",
        "brief": {"SAFE": "favourable for fishing.", "CAUTION": "borderline, proceed carefully.",
                  "UNSAFE": "unsafe, avoid venturing out.", "EXTREME": "severe, do not venture out.",
                  "CRITICAL": "severe, do not venture out."},
    },
}


def _pfz_labels(language: str | None):
    return _PFZ_LABELS.get((language or "en").lower(), _PFZ_LABELS["en"])


# Localized verdict status word (SAFE/CAUTION/UNSAFE) — falls back to the
# English token so an untranslated language still renders correctly.
_VERDICT_WORD = {
    "hi": {"SAFE": "सुरक्षित", "CAUTION": "सावधानी", "UNSAFE": "असुरक्षित", "EXTREME": "अत्यधिक खतरा", "CRITICAL": "गंभीर"},
    "mr": {"SAFE": "सुरक्षित", "CAUTION": "सावधगिरी", "UNSAFE": "असुरक्षित", "EXTREME": "अति धोका", "CRITICAL": "गंभीर"},
    "ta": {"SAFE": "பாதுகாப்பானது", "CAUTION": "எச்சரிக்கை", "UNSAFE": "பாதுகாப்பற்றது", "EXTREME": "மிகுந்த ஆபத்து", "CRITICAL": "நெருக்கடி"},
    "te": {"SAFE": "సురక్షితం", "CAUTION": "జాగ్రత్త", "UNSAFE": "అసురక్షితం", "EXTREME": "అత్యంత ప్రమాదం", "CRITICAL": "క్లిష్టం"},
    "ml": {"SAFE": "സുരക്ഷിതം", "CAUTION": "ജാഗ്രത", "UNSAFE": "സുരക്ഷിതമല്ല", "EXTREME": "അതീവ അപകടം", "CRITICAL": "ഗുരുതരം"},
    "kn": {"SAFE": "ಸುರಕ್ಷಿತ", "CAUTION": "ಎಚ್ಚರಿಕೆ", "UNSAFE": "ಅಸುರಕ್ಷಿತ", "EXTREME": "ತೀವ್ರ ಅಪಾಯ", "CRITICAL": "ಗಂಭೀರ"},
    "gu": {"SAFE": "સલામત", "CAUTION": "સાવધાની", "UNSAFE": "અસલામત", "EXTREME": "અતિ જોખમ", "CRITICAL": "ગંભીર"},
    "bn": {"SAFE": "নিরাপদ", "CAUTION": "সতর্কতা", "UNSAFE": "অনিরাপদ", "EXTREME": "অত্যধিক বিপদ", "CRITICAL": "গুরুতর"},
    "or": {"SAFE": "ନିରାପଦ", "CAUTION": "ସତର୍କତା", "UNSAFE": "ଅସୁରକ୍ଷିତ", "EXTREME": "ଅତ୍ୟଧିକ ବିପଦ", "CRITICAL": "ଗୁରୁତର"},
    "pa": {"SAFE": "ਸੁਰੱਖਿਅਤ", "CAUTION": "ਸਾਵਧਾਨੀ", "UNSAFE": "ਅਸੁਰੱਖਿਅਤ", "EXTREME": "ਬਹੁਤ ਖ਼ਤਰਾ", "CRITICAL": "ਗੰਭੀਰ"},
    "kok": {"SAFE": "सुरक्षित", "CAUTION": "सावधगिरी", "UNSAFE": "असुरक्षित", "EXTREME": "अति धोका", "CRITICAL": "गंभीर"},
    "tcy": {"SAFE": "ಸುರಕ್ಷಿತ", "CAUTION": "ಎಚ್ಚರಿಕೆ", "UNSAFE": "ಅಸುರಕ್ಷಿತ", "EXTREME": "ತೀವ್ರ ಅಪಾಯ", "CRITICAL": "ಗಂಭೀರ"},
    "kfr": {"SAFE": "સલામત", "CAUTION": "સાવધાની", "UNSAFE": "અસલામત", "EXTREME": "અતિ જોખમ", "CRITICAL": "ગંભીર"},
    "byr": {"SAFE": "ಸುರಕ್ಷಿತ", "CAUTION": "ಎಚ್ಚರಿಕೆ", "UNSAFE": "ಅಸುರಕ್ಷಿತ", "EXTREME": "ತೀವ್ರ ಅಪಾಯ", "CRITICAL": "ಗಂಭೀರ"},
    "mvv": {"SAFE": "सुरक्षित", "CAUTION": "सावधगिरी", "UNSAFE": "असुरक्षित", "EXTREME": "अति धोका", "CRITICAL": "गंभीर"},
    "ncr": {"SAFE": "SAFE", "CAUTION": "CAUTION", "UNSAFE": "UNSAFE", "EXTREME": "EXTREME", "CRITICAL": "CRITICAL"},
    "adm": {"SAFE": "SAFE", "CAUTION": "CAUTION", "UNSAFE": "UNSAFE", "EXTREME": "EXTREME", "CRITICAL": "CRITICAL"},
}


def _verdict_word(verdict: str, language: str | None) -> str:
    return _VERDICT_WORD.get((language or "en").lower(), {}).get(verdict, verdict)

# Keywords mirroring orchestrator/planning.py PFZ_LOOKUP routing so the
# exact-template answer is only used when the user actually asked where
# the fish are (never hijacks a safety-check answer).
_PFZ_LOOKUP_KEYWORDS = (
    "fishing zone", "fish zone", "fish zones", "pfz",
    "where to fish", "where can i fish", "nearest fishing",
    "fishing spot", "fishing grounds", "where are the fish",
)


def is_pfz_lookup_query(raw_query: str) -> bool:
    """True when the user's question is asking for a fishing zone."""
    q = (raw_query or "").lower()
    return any(k in q for k in _PFZ_LOOKUP_KEYWORDS)


def bearing_word(deg: float) -> str:
    """225.0 -> 'South-West'."""
    if deg is None:
        return "North"
    return _COMPASS[int((float(deg) % 360) / 45) % 8]


def verdict_brief(verdict: str | None) -> str:
    return _VERDICT_BRIEF.get(
        str(verdict or "").upper(), "Borderline conditions; proceed carefully."
    )


def format_pfz_answer(pfz, verdict: str | None = "CAUTION", narrative: str | None = None,
                      language: str | None = "en") -> str | None:
    """Compact, fully-localized PFZ answer.

    Shows only the essentials the user asked for: the AI summary, the verdict,
    the exact target coordinates, water depth and the honest source tag. The
    verbose duplicated landmark line and the multi-section Target/Quick-Summary
    scaffolding are dropped (spec: "only show imp info and the summary").

    ``narrative`` — LLM-generated, query-specific summary (already in the user's
    language). ``language`` localizes the fixed scaffolding words so the WHOLE
    answer reads in that language, not just the narrative. All numbers/coords
    come straight from the PFZRecommendation.
    """
    if pfz is None:
        return None
    L = _pfz_labels(language)
    source = getattr(pfz, "source", None)
    src_val = getattr(source, "value", source) if source else "unknown"
    is_official = src_val == "incois_live"

    dist_km = float(getattr(pfz, "distance_from_reference_km", 0.0))
    bearing = float(getattr(pfz, "bearing_deg", 0.0))
    lat = float(getattr(pfz, "center_lat", 0.0))
    lon = float(getattr(pfz, "center_lon", 0.0))
    lc = getattr(pfz, "landing_center", None) or {}
    depth = lc.get("advisory_depth_m")
    try:
        depth_txt = f"{float(depth):g} m"
    except (TypeError, ValueError):
        depth_txt = f"{depth} m" if depth is not None else "—"

    verdict_txt = str(verdict or "CAUTION").upper()
    brief = L["brief"].get(verdict_txt, L["brief"]["CAUTION"])
    lat_s = "S" if lat < 0 else "N"
    lon_s = "W" if lon < 0 else "E"
    coord = f"{abs(lat):.4f}° {lat_s}, {abs(lon):.4f}° {lon_s}"
    src = L["source_official"] if is_official else L["source_estimated"]

    parts = []
    if narrative and narrative.strip():
        parts.append(narrative.strip())
    parts.append(f"🔶 {L['verdict']}: {_verdict_word(verdict_txt, language)} — {brief}")
    parts.append(
        f"🎯 {coord}  ·  {L['distance']}: {dist_km:.1f} km ({bearing:.0f}°)  ·  {L['depth']}: {depth_txt}"
    )
    parts.append(f"📡 {src}")
    return "\n\n".join(parts)