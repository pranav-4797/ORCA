"""
Shared i18n fallback for deterministic (LLM-down) answer templates.

When the Groq LLM is unavailable, ORCA cannot call the narrative or
response LLM for a fully natural translation, but the user must still
receive an answer in the language they asked in — not English.
This module supplies lightweight, honest translations for the fixed
scaffolding that deterministic templates emit (verdict words, headings,
table labels, recommendation sentences). Numbers, units, coordinates and
proper nouns (INCOIS, SAMUDRA, place names) stay verbatim.

Coverage: 10 major coastal languages + 7 extra coastal micro-languages
listed in LanguageAgent.SUPPORTED_LANGUAGES. Extra codes fall back to
their closest major language (kok→mr, tcy→kn, kfr→gu/hi, byr→kn, mvv→mr,
ncr/adm→en) but have their own entry so callers never get a KeyError.
"""

from __future__ import annotations

# Map extra coastal codes to a fallback major language for templates
_FALLBACK = {
    "kok": "mr",   # Konkani -> Marathi (closest)
    "tcy": "kn",   # Tulu -> Kannada (same script)
    "kfr": "gu",   # Kutchi -> Gujarati
    "byr": "kn",   # Beary -> Kannada/Malayalam; choose Kannada
    "mvv": "mr",   # Malvani -> Marathi
    "ncr": "en",
    "adm": "en",
}

def _norm(lang: str | None) -> str:
    l = (lang or "en").lower().strip()
    return _FALLBACK.get(l, l)

# ------------------------------------------------------------------
# Language names for prompts (used by narrative/response)
# ------------------------------------------------------------------
LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil",
    "te": "Telugu", "bn": "Bengali", "ml": "Malayalam", "kn": "Kannada",
    "gu": "Gujarati", "or": "Odia", "pa": "Punjabi",
    "kok": "Konkani", "tcy": "Tulu", "kfr": "Kutchi", "byr": "Beary",
    "mvv": "Malvani", "ncr": "Nicobarese", "adm": "Andamanese",
}

# ------------------------------------------------------------------
# Verdict words
# ------------------------------------------------------------------
VERDICT_WORD = {
    "en": {"SAFE": "SAFE", "CAUTION": "CAUTION", "UNSAFE": "UNSAFE", "EXTREME": "EXTREME", "CRITICAL": "CRITICAL"},
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
}

# Extend VERDICT_WORD for fallback codes
for _code, _base in _FALLBACK.items():
    if _code not in VERDICT_WORD:
        VERDICT_WORD[_code] = VERDICT_WORD.get(_base, VERDICT_WORD["en"])

def verdict_word(verdict: str, lang: str | None) -> str:
    v = (verdict or "CAUTION").upper()
    return VERDICT_WORD.get(_norm(lang), VERDICT_WORD["en"]).get(v, v)

# ------------------------------------------------------------------
# Headings
# ------------------------------------------------------------------
HEADINGS = {
    "en": {"marine_conditions": "Marine Conditions", "tourism": "Coastal Points of Interest", "trend": "Trend"},
    "hi": {"marine_conditions": "समुद्री स्थितियां", "tourism": "तटीय दर्शनीय स्थल", "trend": "रुझान"},
    "mr": {"marine_conditions": "सागरी परिस्थिती", "tourism": "किनारी पर्यटन स्थळे", "trend": "कल"},
    "ta": {"marine_conditions": "கடல் நிலைமைகள்", "tourism": "கடற்கரை சுற்றுலா இடங்கள்", "trend": "போக்கு"},
    "te": {"marine_conditions": "సముద్ర పరిస్థితులు", "tourism": "తీరప్రాంత పర్యాటక ప్రదేశాలు", "trend": "ధోరణి"},
    "ml": {"marine_conditions": "സമുദ്ര അവസ്ഥകൾ", "tourism": "തീരദേശ വിനോദസഞ്ചാര കേന്ദ്രങ്ങൾ", "trend": "പ്രവണത"},
    "kn": {"marine_conditions": "ಸಮುದ್ರ ಪರಿಸ್ಥಿತಿಗಳು", "tourism": "ಕರಾವಳಿ ಪ್ರವಾಸಿ ತಾಣಗಳು", "trend": "ಪ್ರವೃತ್ತಿ"},
    "gu": {"marine_conditions": "દરિયાઈ પરિસ્થિતિઓ", "tourism": "કિનારાના પ્રવાસન સ્થળો", "trend": "વલણ"},
    "bn": {"marine_conditions": "সামুদ্রিক অবস্থা", "tourism": "উপকূলীয় দর্শনীয় স্থান", "trend": "প্রবণতা"},
    "or": {"marine_conditions": "ସାମୁଦ୍ରିକ ଅବସ୍ଥା", "tourism": "ଉପକୂଳ ପର୍ଯ୍ୟଟନ ସ୍ଥଳ", "trend": "ପ୍ରବୃତ୍ତି"},
    "pa": {"marine_conditions": "ਸਮੁੰਦਰੀ ਹਾਲਾਤ", "tourism": "ਤੱਟੀ ਸੈਰ-ਸਪਾਟਾ ਸਥਾਨ", "trend": "ਰੁਝਾਨ"},
}
for _code, _base in _FALLBACK.items():
    if _code not in HEADINGS:
        HEADINGS[_code] = HEADINGS.get(_base, HEADINGS["en"])

def heading(key: str, lang: str | None) -> str:
    return HEADINGS.get(_norm(lang), HEADINGS["en"]).get(key, HEADINGS["en"].get(key, key))

# ------------------------------------------------------------------
# Table labels
# ------------------------------------------------------------------
PARAM_LABELS = {
    "en": {"sst": "SST", "wind": "Wind", "waves": "Waves", "swell": "Swell", "current": "Current", "chlorophyll": "Chlorophyll", "tide": "Tide", "parameter": "Parameter", "value": "Value", "type": "Type", "safety": "Safety", "details": "Details", "poi": "POI"},
    "hi": {"sst": "समुद्र सतह तापमान", "wind": "हवा", "waves": "लहरें", "swell": "सूजन", "current": "धारा", "chlorophyll": "क्लोरोफिल", "tide": "ज्वार", "parameter": "मापदंड", "value": "मान", "type": "प्रकार", "safety": "सुरक्षा", "details": "विवरण", "poi": "स्थल"},
    "mr": {"sst": "समुद्र पृष्ठभाग तापमान", "wind": "वारा", "waves": "लाटा", "swell": "उधान", "current": "प्रवाह", "chlorophyll": "क्लोरोफिल", "tide": "भरती", "parameter": "मापदंड", "value": "मूल्य", "type": "प्रकार", "safety": "सुरक्षितता", "details": "तपशील", "poi": "स्थळ"},
    "ta": {"sst": "கடல் மேற்பரப்பு வெப்பநிலை", "wind": "காற்று", "waves": "அலைகள்", "swell": "எழுச்சி", "current": "நீரோட்டம்", "chlorophyll": "குளோரோபில்", "tide": "ஓதம்", "parameter": "அளவுரு", "value": "மதிப்பு", "type": "வகை", "safety": "பாதுகாப்பு", "details": "விவரங்கள்", "poi": "இடம்"},
    "te": {"sst": "సముద్ర ఉపరితల ఉష్ణోగ్రత", "wind": "గాలి", "waves": "అలలు", "swell": "ఉప్పొంగు", "current": "ప్రవాహం", "chlorophyll": "క్లోరోఫిల్", "tide": "ఆటుపోటు", "parameter": "పరామితి", "value": "విలువ", "type": "రకం", "safety": "భద్రత", "details": "వివరాలు", "poi": "ప్రదేశం"},
    "ml": {"sst": "കടൽ ഉപരിതല താപനില", "wind": "കാറ്റ്", "waves": "തിരമാലകൾ", "swell": "വീക്കം", "current": "ഒഴുക്ക്", "chlorophyll": "ക്ലോറോഫിൽ", "tide": "വേലിയേറ്റം", "parameter": "പാരാമീറ്റർ", "value": "മൂല്യം", "type": "തരം", "safety": "സുരക്ഷ", "details": "വിശദാംശങ്ങൾ", "poi": "സ്ഥലം"},
    "kn": {"sst": "ಸಮುದ್ರ ಮೇಲ್ಮೈ ತಾಪಮಾನ", "wind": "ಗಾಳಿ", "waves": "ಅಲೆಗಳು", "swell": "ಉಬ್ಬರ", "current": "ಪ್ರವಾಹ", "chlorophyll": "ಕ್ಲೋರೊಫಿಲ್", "tide": "ಉಬ್ಬರವಿಳಿತ", "parameter": "ನಿಯತಾಂಕ", "value": "ಮೌಲ್ಯ", "type": "ಪ್ರಕಾರ", "safety": "ಸುರಕ್ಷತೆ", "details": "ವಿವರಗಳು", "poi": "ತಾಣ"},
    "gu": {"sst": "દરિયાની સપાટીનું તાપમાન", "wind": "પવન", "waves": "મોજા", "swell": "ઉછાળો", "current": "પ્રવાહ", "chlorophyll": "ક્લોરોફિલ", "tide": "ભરતી", "parameter": "પરિમાણ", "value": "મૂલ્ય", "type": "પ્રકાર", "safety": "સલામતી", "details": "વિગતો", "poi": "સ્થળ"},
    "bn": {"sst": "সমুদ্র পৃষ্ঠের তাপমাত্রা", "wind": "বাতাস", "waves": "ঢেউ", "swell": "ফোলা", "current": "স্রোত", "chlorophyll": "ক্লোরোফিল", "tide": "জোয়ার", "parameter": "প্যারামিটার", "value": "মান", "type": "ধরন", "safety": "নিরাপত্তা", "details": "বিবরণ", "poi": "স্থান"},
    "or": {"sst": "ସମୁଦ୍ର ପୃଷ୍ଠ ତାପମାତ୍ରା", "wind": "ପବନ", "waves": "ତରଙ୍ଗ", "swell": "ଫୁଲା", "current": "ସ୍ରୋତ", "chlorophyll": "କ୍ଲୋରୋଫିଲ", "tide": "ଜୁଆର", "parameter": "ମାପଦଣ୍ଡ", "value": "ମୂଲ୍ୟ", "type": "ପ୍ରକାର", "safety": "ନିରାପତ୍ତା", "details": "ବିବରଣୀ", "poi": "ସ୍ଥାନ"},
    "pa": {"sst": "ਸਮੁੰਦਰ ਸਤਹਿ ਤਾਪਮਾਨ", "wind": "ਹਵਾ", "waves": "ਲਹਿਰਾਂ", "swell": "ਸੋਜ", "current": "ਵਹਾਅ", "chlorophyll": "ਕਲੋਰੋਫਿਲ", "tide": "ਜਵਾਰ", "parameter": "ਪੈਰਾਮੀਟਰ", "value": "ਮੁੱਲ", "type": "ਕਿਸਮ", "safety": "ਸੁਰੱਖਿਆ", "details": "ਵੇਰਵੇ", "poi": "ਥਾਂ"},
}
for _code, _base in _FALLBACK.items():
    if _code not in PARAM_LABELS:
        PARAM_LABELS[_code] = PARAM_LABELS.get(_base, PARAM_LABELS["en"])

def param_label(key: str, lang: str | None) -> str:
    return PARAM_LABELS.get(_norm(lang), PARAM_LABELS["en"]).get(key, key)

# ------------------------------------------------------------------
# Source word (localized)
# ------------------------------------------------------------------
SOURCE_WORD = {
    "en": "Source", "hi": "स्रोत", "mr": "स्रोत", "ta": "ஆதாரம்", "te": "మూలం", "bn": "উৎস",
    "ml": "ഉറവിടം", "kn": "ಮೂಲ", "gu": "સ્રોત", "or": "ଉତ୍ସ", "pa": "ਸਰੋਤ",
}
for _code, _base in _FALLBACK.items():
    if _code not in SOURCE_WORD:
        SOURCE_WORD[_code] = SOURCE_WORD.get(_base, SOURCE_WORD["en"])

def source_word(lang: str | None) -> str:
    return SOURCE_WORD.get(_norm(lang), SOURCE_WORD["en"])

SOURCE_PROVENANCE = "Official INCOIS Ocean State Forecast + OceanSat-2 + Gemini PFZ"

def source_line(lang: str | None) -> str:
    return f"*{source_word(lang)}: {SOURCE_PROVENANCE}*"

# ------------------------------------------------------------------
# Recommendation sentences (SST-only, wind-only, wave-only, generic)
# ------------------------------------------------------------------
# Minimal set — the deterministic fallback picks one of these based on the
# query-aware field filter. Kept short so they can be translated without
# inventing new facts; numbers are interpolated by the caller.
RECOMMENDATIONS = {
    "en": {
        "sst_only": "SST is {v}°C at this location — the sea surface is warm; monitor for rapid temperature changes that can affect fish movement and vessel comfort.",
        "sst_missing": "Monitor the sea-surface temperature closely and be prepared for possible rapid changes that could affect vessel performance.",
        "wind_strong": "Wind is {v} km/h {d} — strong with noticeable chop; small craft handling will be affected. Delay departure or proceed with extra caution.",
        "wind_mod": "Wind is {v} km/h {d} — moderate with a gentle surface chop. It can affect small craft handling, so proceed with caution.",
        "wind_light": "Wind is {v} km/h {d} — light and generally favorable for handling, but keep monitoring for sudden gusts.",
        "wave": "Waves are {v} m at this location — even moderate seas can impact small vessels. Proceed carefully and keep monitoring the swell.",
        "wave_missing": "Monitor wave/swell heights closely — even moderate seas can impact small vessels; proceed carefully.",
        "current": "Surface current is {v} m/s — account for drift in navigation and fishing operations.",
        "current_missing": "Surface currents are present — account for drift in navigation and fishing operations.",
        "generic_safe": "{vals}Conditions are generally favorable — suitable for venturing out, but keep monitoring official updates.",
        "generic_unsafe": "{vals}Conditions are unsafe — avoid venturing out and wait for improvement in wind/wave parameters.",
        "generic_caution": "{vals}Borderline conditions — proceed carefully, keep monitoring for rapid changes, and stay within safe limits for your vessel class.",
    },
    "hi": {
        "sst_only": "इस स्थान पर SST {v}°C है — समुद्र सतह गर्म है; मछली की आवाजाही और नाव की सुविधा को प्रभावित करने वाले तेज़ तापमान बदलावों पर नज़र रखें।",
        "sst_missing": "समुद्र सतह के तापमान पर बारीकी से नज़र रखें और संभावित तेज़ बदलावों के लिए तैयार रहें।",
        "wind_strong": "हवा {v} किमी/घंटा {d} — तेज़ और लहरों के साथ; छोटी नावों की हैंडलिंग प्रभावित होगी। प्रस्थान टालें या अतिरिक्त सावधानी बरतें।",
        "wind_mod": "हवा {v} किमी/घंटा {d} — मध्यम, हल्की लहरों के साथ। छोटी नावों पर असर पड़ सकता है, सावधानी से आगे बढ़ें।",
        "wind_light": "हवा {v} किमी/घंटा {d} — हल्की और आम तौर पर अनुकूल, लेकिन अचानक झोंकों पर नज़र रखें।",
        "wave": "लहरें {v} मी हैं — मध्यम समुद्र भी छोटी नावों को प्रभावित कर सकता है। सावधानी से आगे बढ़ें और सूजन पर नज़र रखें।",
        "wave_missing": "लहर/सूजन की ऊँचाई पर नज़र रखें — मध्यम समुद्र भी छोटी नावों को प्रभावित कर सकता है।",
        "current": "सतह धारा {v} मी/से है — नेविगेशन और मछली पकड़ने में बहाव का ध्यान रखें।",
        "current_missing": "सतह धाराएँ मौजूद हैं — नेविगेशन में बहाव का ध्यान रखें।",
        "generic_safe": "{vals}परिस्थितियाँ आम तौर पर अनुकूल हैं — बाहर जाने योग्य, लेकिन आधिकारिक अपडेट पर नज़र रखें।",
        "generic_unsafe": "{vals}परिस्थितियाँ असुरक्षित हैं — बाहर न जाएँ और हवा/लहर में सुधार का इंतज़ार करें।",
        "generic_caution": "{vals}सीमावर्ती परिस्थितियाँ — सावधानी से आगे बढ़ें, तेज़ बदलावों पर नज़र रखें।",
    },
    "mr": {
        "sst_only": "या ठिकाणी SST {v}°C आहे — समुद्र पृष्ठभाग उबदार आहे; माशांच्या हालचालींवर परिणाम करणाऱ्या तापमान बदलांवर लक्ष ठेवा।",
        "sst_missing": "समुद्र पृष्ठभागाच्या तापमानावर बारीक लक्ष ठेवा आणि संभाव्य बदलांसाठी तयार रहा।",
        "wind_strong": "वारा {v} किमी/तास {d} — जोरदार, लाटांसह; लहान बोटींचे नियंत्रण प्रभावित होईल. प्रस्थान पुढे ढकला किंवा अतिरिक्त काळजी घ्या।",
        "wind_mod": "वारा {v} किमी/तास {d} — मध्यम, हलक्या लाटांसह. लहान बोटींवर परिणाम होऊ शकतो, काळजीपूर्वक जा।",
        "wind_light": "वारा {v} किमी/तास {d} — हलका आणि अनुकूल, पण अचानक झोतांवर लक्ष ठेवा।",
        "wave": "लाटा {v} मी आहेत — मध्यम समुद्रही लहान बोटींना प्रभावित करू शकतो. काळजीपूर्वक पुढे जा।",
        "wave_missing": "लाटा/उधाण उंचीवर लक्ष ठेवा — मध्यम समुद्रही लहान बोटींना प्रभावित करू शकतो।",
        "current": "पृष्ठभाग प्रवाह {v} मी/से आहे — नेव्हिगेशनमध्ये वाहून जाण्याचा विचार करा।",
        "current_missing": "पृष्ठभाग प्रवाह आहेत — नेव्हिगेशनमध्ये वाहून जाण्याचा विचार करा।",
        "generic_safe": "{vals}परिस्थिती अनुकूल आहे — बाहेर जाण्यास योग्य, पण अद्ययावत माहितीवर लक्ष ठेवा।",
        "generic_unsafe": "{vals}परिस्थिती असुरक्षित आहे — बाहेर जाऊ नका, वारा/लाट सुधारण्याची वाट पहा।",
        "generic_caution": "{vals}सीमारेषीय परिस्थिती — काळजीपूर्वक जा, बदलांवर लक्ष ठेवा।",
    },
    "ta": {
        "sst_only": "இந்த இடத்தில் SST {v}°C — கடல் மேற்பரப்பு சூடாக உள்ளது; மீன் நடமாட்டத்தை பாதிக்கும் வெப்பநிலை மாற்றங்களை கண்காணிக்கவும்.",
        "sst_missing": "கடல் மேற்பரப்பு வெப்பநிலையை கவனமாக கண்காணித்து திடீர் மாற்றங்களுக்கு தயாராக இருக்கவும்.",
        "wind_strong": "காற்று {v} கிமீ/மணி {d} — வலுவானது, அலைகளுடன்; சிறு படகு கையாளுதல் பாதிக்கப்படும். புறப்படுவதை தள்ளிவைக்கவும்.",
        "wind_mod": "காற்று {v} கிமீ/மணி {d} — மிதமானது, லேசான அலைகளுடன். சிறு படகுகளில் தாக்கம் இருக்கும்.",
        "wind_light": "காற்று {v} கிமீ/மணி {d} — லேசானது மற்றும் சாதகமானது, திடீர் காற்று வீச்சுகளை கவனிக்கவும்.",
        "wave": "அலைகள் {v} மீ — மிதமான கடலும் சிறு படகுகளை பாதிக்கும். கவனமாக செல்லவும்.",
        "wave_missing": "அலை/எழுச்சி உயரத்தை கண்காணிக்கவும் — மிதமான கடலும் சிறு படகுகளை பாதிக்கும்.",
        "current": "மேற்பரப்பு நீரோட்டம் {v} மீ/வி — வழிசெலுத்தலில் இழுப்பை கணக்கில் கொள்ளவும்.",
        "current_missing": "மேற்பரப்பு நீரோட்டம் உள்ளது — வழிசெலுத்தலில் இழுப்பை கணக்கில் கொள்ளவும்.",
        "generic_safe": "{vals}நிலைமைகள் சாதகமானவை — வெளியே செல்லலாம், அதிகாரப்பூர்வ தகவல்களை கண்காணிக்கவும்.",
        "generic_unsafe": "{vals}நிலைமைகள் பாதுகாப்பற்றவை — வெளியே செல்ல வேண்டாம்.",
        "generic_caution": "{vals}எல்லைநிலை — கவனமாக செல்லவும், மாற்றங்களை கண்காணிக்கவும்.",
    },
    "te": {
        "sst_only": "ఈ ప్రదేశంలో SST {v}°C — సముద్ర ఉపరితలం వెచ్చగా ఉంది; చేపల కదలికను ప్రభావితం చేసే ఉష్ణోగ్రత మార్పులను గమనించండి.",
        "sst_missing": "సముద్ర ఉపరితల ఉష్ణోగ్రతను నిశితంగా గమనించండి.",
        "wind_strong": "గాలి {v} కిమీ/గం {d} — బలంగా, అలలతో; చిన్న పడవల నియంత్రణ ప్రభావితమవుతుంది. ప్రయాణం వాయిదా వేయండి.",
        "wind_mod": "గాలి {v} కిమీ/గం {d} — మధ్యస్థం, తేలికపాటి అలలతో. జాగ్రత్తగా వెళ్లండి.",
        "wind_light": "గాలి {v} కిమీ/గం {d} — తేలికపాటిది, అనుకూలం, ఆకస్మిక గాలులను గమనించండి.",
        "wave": "అలలు {v} మీ — మధ్యస్థ సముద్రం కూడా చిన్న పడవలను ప్రభావితం చేస్తుంది.",
        "wave_missing": "అల/ఉప్పొంగు ఎత్తును గమనించండి.",
        "current": "ఉపరితల ప్రవాహం {v} మీ/సె — నావిగేషన్‌లో కొట్టుకుపోవడాన్ని పరిగణించండి.",
        "current_missing": "ఉపరితల ప్రవాహాలు ఉన్నాయి — కొట్టుకుపోవడాన్ని పరిగణించండి.",
        "generic_safe": "{vals}పరిస్థితులు అనుకూలంగా ఉన్నాయి — బయటకు వెళ్ళవచ్చు.",
        "generic_unsafe": "{vals}పరిస్థితులు అసురక్షితం — బయటకు వెళ్లవద్దు.",
        "generic_caution": "{vals}సరిహద్దు పరిస్థితులు — జాగ్రత్తగా వెళ్లండి.",
    },
    "kn": {
        "sst_only": "ಈ ಸ್ಥಳದಲ್ಲಿ SST {v}°C — ಸಮುದ್ರ ಮೇಲ್ಮೈ ಬೆచ్చಗಿದೆ; ಮೀನು ಚಲನೆಯನ್ನು ಪ್ರಭಾವಿಸುವ ತಾಪಮಾನ ಬದಲಾವಣೆಗಳನ್ನು ಗಮನಿಸಿ.",
        "sst_missing": "ಸಮುದ್ರ ಮೇಲ್ಮೈ ತಾಪಮಾನವನ್ನು ಸೂಕ್ಷ್ಮವಾಗಿ ಗಮನಿಸಿ.",
        "wind_strong": "ಗಾಳಿ {v} ಕಿಮೀ/ಗಂ {d} — ಬಲವಾದ, ಅಲೆಗಳೊಂದಿಗೆ; ಸಣ್ಣ ದೋಣಿ ನಿಯಂತ್ರಣ ಪ್ರಭಾವಿತವಾಗುತ್ತದೆ. ಪ್ರಯಾಣ ಮುಂದೂಡಿ.",
        "wind_mod": "ಗಾಳಿ {v} ಕಿಮೀ/ಗಂ {d} — ಮಧ್ಯಮ, ಲಘು ಅಲೆಗಳೊಂದಿಗೆ. ಎಚ್ಚರಿಕೆಯಿಂದ ಸಾಗಿ.",
        "wind_light": "ಗಾಳಿ {v} ಕಿಮೀ/ಗಂ {d} — ಲಘು ಮತ್ತು ಅನುಕೂಲಕರ, ಹಠಾತ್ ಗಾಳಿಯನ್ನು ಗಮನಿಸಿ.",
        "wave": "ಅಲೆಗಳು {v} ಮೀ — ಮಧ್ಯಮ ಸಮುದ್ರವೂ ಸಣ್ಣ ದೋಣಿಗಳನ್ನು ಪ್ರಭಾವಿಸುತ್ತದೆ.",
        "wave_missing": "ಅಲೆ/ಉಬ್ಬರ ಎತ್ತರವನ್ನು ಗಮನಿಸಿ.",
        "current": "ಮೇಲ್ಮೈ ಪ್ರವಾಹ {v} ಮೀ/ಸೆ — ಸಂಚರಣೆಯಲ್ಲಿ ಕೊಚ್ಚಿಹೋಗುವಿಕೆಯನ್ನು ಪರಿಗಣಿಸಿ.",
        "current_missing": "ಮೇಲ್ಮೈ ಪ್ರವಾಹಗಳಿವೆ — ಕೊಚ್ಚಿಹೋಗುವಿಕೆಯನ್ನು ಪರಿಗಣಿಸಿ.",
        "generic_safe": "{vals}ಪರಿಸ್ಥಿತಿಗಳು ಅನುಕೂಲಕರವಾಗಿವೆ — ಹೊರಗೆ ಹೋಗಬಹುದು.",
        "generic_unsafe": "{vals}ಪರಿಸ್ಥಿತಿಗಳು ಅಸುರಕ್ಷಿತ — ಹೊರಗೆ ಹೋಗಬೇಡಿ.",
        "generic_caution": "{vals}ಗಡಿರೇಖೆ ಪರಿಸ್ಥಿತಿ — ಎಚ್ಚರಿಕೆಯಿಂದ ಸಾಗಿ.",
    },
    "ml": {
        "sst_only": "ഈ സ്ഥലത്ത് SST {v}°C — കടൽ ഉപരിതലം ചൂടാണ്; മത്സ്യചലനത്തെ ബാധിക്കുന്ന താപനില മാറ്റങ്ങൾ നിരീക്ഷിക്കുക.",
        "sst_missing": "കടൽ ഉപരിതല താപനില സൂക്ഷ്മമായി നിരീക്ഷിക്കുക.",
        "wind_strong": "കാറ്റ് {v} കിമീ/മ {d} — ശക്തമായ, തിരമാലകളോടെ; ചെറിയ വള്ളം നിയന്ത്രണം ബാധിക്കും. യാത്ര മാറ്റിവയ്ക്കുക.",
        "wind_mod": "കാറ്റ് {v} കിമീ/മ {d} — മിതമായ, നേരിയ തിരകളോടെ. ശ്രദ്ധയോടെ പോകുക.",
        "wind_light": "കാറ്റ് {v} കിമീ/മ {d} — ലഘുവും അനുകൂലവും, പെട്ടെന്നുള്ള കാറ്റിനെ ശ്രദ്ധിക്കുക.",
        "wave": "തിരമാലകൾ {v} മീ — മിതമായ കടലും ചെറിയ വള്ളങ്ങളെ ബാധിക്കും.",
        "wave_missing": "തിര/വീക്കം ഉയരം നിരീക്ഷിക്കുക.",
        "current": "ഉപരിതല ഒഴുക്ക് {v} മീ/സെ — നാവിഗേഷനിൽ ഒഴുക്കിനെ പരിഗണിക്കുക.",
        "current_missing": "ഉപരിതല ഒഴുക്കുകളുണ്ട് — ഒഴുക്കിനെ പരിഗണിക്കുക.",
        "generic_safe": "{vals}അവസ്ഥകൾ അനുകൂലമാണ് — പുറത്തു പോകാം.",
        "generic_unsafe": "{vals}അവസ്ഥകൾ സുരക്ഷിതമല്ല — പുറത്തു പോകരുത്.",
        "generic_caution": "{vals}അതിർത്തಿ അവസ്ഥ — ശ്രദ്ധയോടെ പോകുക.",
    },
    "gu": {
        "sst_only": "આ સ્થળે SST {v}°C છે — દરિયાની સપાટી ગરમ છે; માછલીની હિલચાલને અસર કરતા તાપમાન ફેરફારો પર નજર રાખો.",
        "sst_missing": "દરિયાની સપાટીના તાપમાન પર બારીક નજર રાખો.",
        "wind_strong": "પવન {v} કિમી/ક {d} — જોરદાર, મોજા સાથે; નાની હોડીનું નિયંત્રણ પ્રભાવિત થશે. પ્રસ્થાન મોકૂફ રાખો.",
        "wind_mod": "પવન {v} કિમી/ક {d} — મધ્યમ, હળવા મોજા સાથે. સાવધાનીથી આગળ વધો.",
        "wind_light": "પવન {v} કિમી/ક {d} — હળવો અને અનુકૂળ, અચાનક પવન પર નજર રાખો.",
        "wave": "મોજા {v} મી છે — મધ્યમ દરિયો પણ નાની હોડીઓને અસર કરી શકે છે.",
        "wave_missing": "મોજા/ઉછાળાની ઊંચાઈ પર નજર રાખો.",
        "current": "સપાટી પ્રવાહ {v} મી/સે છે — નેવિગેશનમાં ઘસડાવાનો વિચાર કરો.",
        "current_missing": "સપાટી પ્રવાહો છે — ઘસડાવાનો વિચાર કરો.",
        "generic_safe": "{vals}પરિસ્થિતિઓ અનુકૂળ છે — બહાર જઈ શકાય છે.",
        "generic_unsafe": "{vals}પરિસ્થિતિઓ અસુરક્ષિત છે — બહાર ન જાઓ.",
        "generic_caution": "{vals}સીમારેખા પરિસ્થિતિ — સાવધાનીથી આગળ વધો.",
    },
    "bn": {
        "sst_only": "এই স্থানে SST {v}°C — সমুদ্র পৃষ্ঠ উষ্ণ; মাছের চলাচলে প্রভাব ফেলে এমন তাপমাত্রা পরিবর্তনে নজর রাখুন।",
        "sst_missing": "সমুদ্র পৃষ্ঠের তাপমাত্রা নিবিড়ভাবে পর্যবেক্ষণ করুন।",
        "wind_strong": "বাতাস {v} কিমি/ঘন্টা {d} — শক্তিশালী, ঢেউ সহ; ছোট নৌকার নিয়ন্ত্রণ প্রভাবিত হবে। যাত্রা স্থগিত করুন।",
        "wind_mod": "বাতাস {v} কিমি/ঘন্টা {d} — মাঝারি, হালকা ঢেউ সহ। সাবধানে এগোন।",
        "wind_light": "বাতাস {v} কিমি/ঘন্টা {d} — হালকা ও অনুকূল, হঠাৎ দমকা হাওয়ায় নজর রাখুন।",
        "wave": "ঢেউ {v} মি — মাঝারি সমুদ্রও ছোট নৌকাকে প্রভাবিত করতে পারে।",
        "wave_missing": "ঢেউ/ফোলা উচ্চতা পর্যবেক্ষণ করুন।",
        "current": "পৃষ্ঠ স্রোত {v} মি/সে — নেভিগেশনে ভেসে যাওয়া বিবেচনা করুন।",
        "current_missing": "পৃষ্ঠ স্রোত রয়েছে — ভেসে যাওয়া বিবেচনা করুন।",
        "generic_safe": "{vals}পরিস্থিতি অনুকূল — বাইরে যাওয়া যায়।",
        "generic_unsafe": "{vals}পরিস্থিতি অনিরাপদ — বাইরে যাবেন না।",
        "generic_caution": "{vals}সীমারেখা পরিস্থিতি — সাবধানে এগোন।",
    },
    "or": {
        "sst_only": "ଏହି ସ୍ଥାନରେ SST {v}°C — ସମୁଦ୍ର ପୃଷ୍ଠ ଗରମ; ମାଛ ଚଳନକୁ ପ୍ରଭାବିତ କରୁଥିବା ତାପମାତ୍ରା ପରିବର୍ତ୍ତନ ଉପରେ ନଜର ରଖନ୍ତୁ।",
        "sst_missing": "ସମୁଦ୍ର ପୃଷ୍ଠ ତାପମାତ୍ରା ଉପରେ ନିବିଡ଼ ନଜର ରଖନ୍ତୁ।",
        "wind_strong": "ପବନ {v} କିମି/ଘଣ୍ଟା {d} — ଶକ୍ତିଶାଳୀ, ତରଙ୍ଗ ସହ; ଛୋଟ ଡଙ୍ଗା ନିୟନ୍ତ୍ରଣ ପ୍ରଭାବିତ ହେବ। ଯାତ୍ରା ସ୍ଥଗିତ ରଖନ୍ତୁ।",
        "wind_mod": "ପବନ {v} କିମି/ଘଣ୍ଟା {d} — ମଧ୍ୟମ, ହାଲୁକା ତରଙ୍ଗ ସହ। ସାବଧାନରେ ଆଗକୁ ବଢ଼ନ୍ତୁ।",
        "wind_light": "ପବନ {v} କିମି/ଘଣ୍ଟା {d} — ହାଲୁକା ଓ ଅନୁକୂଳ, ହଠାତ୍ ପବନ ଉପରେ ନଜର ରଖନ୍ତୁ।",
        "wave": "ତରଙ୍ଗ {v} ମି — ମଧ୍ୟମ ସମୁଦ୍ର ମଧ୍ୟ ଛୋଟ ଡଙ୍ଗାକୁ ପ୍ରଭାବିତ କରିପାରେ।",
        "wave_missing": "ତରଙ୍ଗ/ଫୁଲା ଉଚ୍ଚତା ଉପରେ ନଜର ରଖନ୍ତୁ।",
        "current": "ପୃଷ୍ଠ ସ୍ରୋତ {v} ମି/ସେ — ନାଭିଗେସନରେ ଭାସିଯିବା ବିଚାର କରନ୍ତୁ।",
        "current_missing": "ପୃଷ୍ଠ ସ୍ରୋତ ଅଛି — ଭାସିଯିବା ବିଚାର କରନ୍ତୁ।",
        "generic_safe": "{vals}ପରିସ୍ଥିତି ଅନୁକୂଳ — ବାହାରକୁ ଯାଇପାରିବେ।",
        "generic_unsafe": "{vals}ପରିସ୍ଥିତି ଅସୁରକ୍ଷିତ — ବାହାରକୁ ଯାଆନ୍ତୁ ନାହିଁ।",
        "generic_caution": "{vals}ସୀମାରେଖା ପରିସ୍ଥିତି — ସାବଧାନରେ ଆଗକୁ ବଢ଼ନ୍ତୁ।",
    },
    "pa": {
        "sst_only": "ਇਸ ਥਾਂ 'ਤੇ SST {v}°C ਹੈ — ਸਮੁੰਦਰ ਸਤਹਿ ਗਰਮ ਹੈ; ਮੱਛੀ ਦੀ ਹਿਲਜੁਲ ਨੂੰ ਪ੍ਰਭਾਵਿਤ ਕਰਨ ਵਾਲੇ ਤਾਪਮਾਨ ਬਦਲਾਅ 'ਤੇ ਨਜ਼ਰ ਰੱਖੋ।",
        "sst_missing": "ਸਮੁੰਦਰ ਸਤਹਿ ਦੇ ਤਾਪਮਾਨ 'ਤੇ ਨੇੜਿਓਂ ਨਜ਼ਰ ਰੱਖੋ।",
        "wind_strong": "ਹਵਾ {v} ਕਿਮੀ/ਘੰਟਾ {d} — ਤੇਜ਼, ਲਹਿਰਾਂ ਨਾਲ; ਛੋਟੀ ਕਿਸ਼ਤੀ ਦਾ ਕੰਟਰੋਲ ਪ੍ਰਭਾਵਿਤ ਹੋਵੇਗਾ। ਰਵਾਨਗੀ ਮੁਲਤਵੀ ਕਰੋ।",
        "wind_mod": "ਹਵਾ {v} ਕਿਮੀ/ਘੰਟਾ {d} — ਦਰਮਿਆਨੀ, ਹਲਕੀਆਂ ਲਹਿਰਾਂ ਨਾਲ। ਸਾਵਧਾਨੀ ਨਾਲ ਅੱਗੇ ਵਧੋ।",
        "wind_light": "ਹਵਾ {v} ਕਿਮੀ/ਘੰਟਾ {d} — ਹਲਕੀ ਅਤੇ ਅਨੁਕੂਲ, ਅਚਾਨਕ ਝੱਖੜ 'ਤੇ ਨਜ਼ਰ ਰੱਖੋ।",
        "wave": "ਲਹਿਰਾਂ {v} ਮੀ ਹਨ — ਦਰਮਿਆਨਾ ਸਮੁੰਦਰ ਵੀ ਛੋਟੀਆਂ ਕਿਸ਼ਤੀਆਂ ਨੂੰ ਪ੍ਰਭਾਵਿਤ ਕਰ ਸਕਦਾ ਹੈ।",
        "wave_missing": "ਲਹਿਰ/ਸੋਜ ਦੀ ਉਚਾਈ 'ਤੇ ਨਜ਼ਰ ਰੱਖੋ।",
        "current": "ਸਤਹਿ ਵਹਾਅ {v} ਮੀ/ਸੈ ਹੈ — ਨੇਵੀਗੇਸ਼ਨ ਵਿੱਚ ਵਹਾਅ ਦਾ ਧਿਆਨ ਰੱਖੋ।",
        "current_missing": "ਸਤਹਿ ਵਹਾਅ ਮੌਜੂਦ ਹਨ — ਵਹਾਅ ਦਾ ਧਿਆਨ ਰੱਖੋ।",
        "generic_safe": "{vals}ਹਾਲਾਤ ਅਨੁਕੂਲ ਹਨ — ਬਾਹਰ ਜਾਇਆ ਜਾ ਸਕਦਾ ਹੈ।",
        "generic_unsafe": "{vals}ਹਾਲਾਤ ਅਸੁਰੱਖਿਅਤ ਹਨ — ਬਾਹਰ ਨਾ ਜਾਓ।",
        "generic_caution": "{vals}ਸੀਮਾਂਤ ਹਾਲਾਤ — ਸਾਵਧਾਨੀ ਨਾਲ ਅੱਗੇ ਵਧੋ।",
    },
}
for _code, _base in _FALLBACK.items():
    if _code not in RECOMMENDATIONS:
        RECOMMENDATIONS[_code] = RECOMMENDATIONS.get(_base, RECOMMENDATIONS["en"])

def recommendation(key: str, lang: str | None, **kwargs) -> str:
    tmpl = RECOMMENDATIONS.get(_norm(lang), RECOMMENDATIONS["en"]).get(key, RECOMMENDATIONS["en"].get(key, ""))
    try:
        return tmpl.format(**kwargs)
    except Exception:
        return tmpl

# Degraded messages already in state.py but expose via i18n for fallback templates
DEGRADED_MESSAGES = {
    "en": "Service is running in limited mode right now, please try again shortly or ask in English.",
    "hi": "सेवा फिलहाल सीमित मोड में चल रही है। कृपया थोड़ी देर बाद पुनः प्रयास करें या अंग्रेज़ी में पूछें।",
    "mr": "सेवा सध्या मर्यादित मोडमध्ये चालू आहे. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा किंवा इंग्रजीत विचारा.",
    "ta": "சேவை தற்போது வரையறுக்கப்பட்ட முறையில் இயங்குகிறது. சிறிது நேரம் கழித்து மீண்டும் முயற்சிக்கவும் அல்லது ஆங்கிலத்தில் கேட்கவும்.",
    "te": "సేవ ప్రస్తుతం పరిమిత మోడ్‌లో నడుస్తోంది. దయచేసి కొద్దిసేపటి తర్వాత మళ్లీ ప్రయత్నించండి లేదా ఆంగ్లంలో అడగండి.",
    "bn": "পরিষেবাটি বর্তমানে সীমিত মোডে চলছে। অনুগ্রহ করে কিছুক্ষণ পরে আবার চেষ্টা করুন বা ইংরেজিতে জিজ্ঞাসা করুন।",
    "ml": "സേവനം ഇപ്പോൾ പരിമിത മോഡിൽ പ്രവർത്തിക്കുന്നു. ദയവായി കുറച്ച് സമയത്തിന് ശേഷം വീണ്ടും ശ്രമിക്കുക അല്ലെങ്കിൽ ഇംഗ്ലീഷിൽ ചോദിക്കുക.",
    "kn": "ಸೇವೆ ಪ್ರಸ್ತುತ ಸೀಮಿತ ಮೋಡ್‌ನಲ್ಲಿ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತಿದೆ. ದಯವಿಟ್ಟು ಸ್ವಲ್ಪ ಸಮಯದ ನಂತರ ಮತ್ತೆ ಪ್ರಯತ್ನಿಸಿ ಅಥವಾ ಇಂಗ್ಲಿಷ್‌ನಲ್ಲಿ ಕೇಳಿ.",
    "gu": "સેવા હાલમાં મર્યાદિત મોડમાં ચાલી રહી છે. કૃપા કરીને થોડા સમય પછી ફરી પ્રયાસ કરો અથવા અંગ્રેજીમાં પૂછો.",
    "or": "ସେବା ବର୍ତ୍ତମାନ ସୀମିତ ମୋଡରେ ଚାଲୁଛି। ଦୟାକରି କିଛି ସମୟ ପରେ ପୁନର୍ବାର ଚେଷ୍ଟା କରନ୍ତୁ କିମ୍ବା ଇଂରାଜୀରେ ପଚାରନ୍ତୁ।",
    "pa": "ਸੇਵਾ ਇਸ ਵੇਲੇ ਸੀਮਤ ਮੋਡ ਵਿੱਚ ਚੱਲ ਰਹੀ ਹੈ। ਕਿਰਪਾ ਕਰਕੇ ਥੋੜ੍ਹੀ ਦੇਰ ਬਾਅਦ ਦੁਬਾਰਾ ਕੋਸ਼ਿਸ਼ ਕਰੋ ਜਾਂ ਅੰਗਰੇਜ਼ੀ ਵਿੱਚ ਪੁੱਛੋ।",
}
for _code, _base in _FALLBACK.items():
    if _code not in DEGRADED_MESSAGES:
        DEGRADED_MESSAGES[_code] = DEGRADED_MESSAGES.get(_base, DEGRADED_MESSAGES["en"])

def degraded_message(lang: str | None) -> str:
    return DEGRADED_MESSAGES.get(_norm(lang), DEGRADED_MESSAGES["en"])
