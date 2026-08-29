export interface I18nContent {
  tabToday: string;
  tabAsk: string;
  tabAuthority: string;
  tabSystem: string;
  askTitle: string;
  askSub: string;
  waves: string;
  wind: string;
  sea: string;
  rain: string;
  vis: string;
  temp: string;
  factorTitle: string;
  officialWarnings: string;
  waveHeight: string;
  windSpeed: string;
  restrictedZones: string;
  safeVerdict: string;
  dangerVerdict: string;
  cautionVerdict: string;
  safeTip: string;
  dangerTip: string;
  cautionTip: string;
  sugg1: string;
  sugg1Q: string;
  sugg2: string;
  sugg2Q: string;
  sugg3: string;
  sugg3Q: string;
  sugg4: string;
  sugg4Q: string;
  composerPlaceholder: string;
  sc1Title: string;
  sc1Sub: string;
  sc1Q: string;
  sc2Title: string;
  sc2Sub: string;
  sc2Q: string;
  sc3Title: string;
  sc3Sub: string;
  sc3Q: string;
  sc4Title: string;
  sc4Sub: string;
  sc4Q: string;
  sc5Title: string;
  sc5Sub: string;
  sc5Q: string;
}

export const I18N: Record<'en' | 'mr' | 'hi', I18nContent> = {
  en: {
    tabToday: 'Overview',
    tabAsk: 'Ask ORCA',
    tabAuthority: 'Authority',
    tabSystem: 'System',
    askTitle: 'Ask ORCA',
    askSub: 'Type or speak your maritime inquiry',
    waves: 'WAVES',
    wind: 'WIND',
    sea: 'SEA',
    rain: 'RAIN',
    vis: 'VISIBILITY',
    temp: 'TEMP',
    factorTitle: 'FACTOR BREAKDOWN',
    officialWarnings: 'Official Warnings & Advisories',
    waveHeight: 'Significant Wave Height',
    windSpeed: 'Wind Speed & Squalls',
    restrictedZones: 'Boundary & Geofence Status',
    safeVerdict: 'Safe to Sail — All Clear',
    dangerVerdict: 'High Hazard — Do Not Sail',
    cautionVerdict: 'Caution — Stay Close to Coast',
    safeTip: 'Conditions are favorable. Keep VHF Ch 16 active.',
    dangerTip: 'Severe hazard active. Conditions may improve after 11:00.',
    cautionTip: 'Moderate chop. Proceed with caution.',
    sugg1: 'Forecast at 12 PM?',
    sugg1Q: 'What is the sea state and wind forecast at 12 PM today?',
    sugg2: 'Show nearest PFZ',
    sugg2Q: 'Where is the nearest official INCOIS Potential Fishing Zone (PFZ) today?',
    sugg3: 'Show safe course',
    sugg3Q: 'Plot a safe navigational route avoiding shallow waters and restricted zones.',
    sugg4: 'Any active storm alerts?',
    sugg4Q: 'Are there active cyclone or squall warnings in this sector?',
    composerPlaceholder: 'Ask anything, type @ for agents, or speak...',
    sc1Title: 'Safe',
    sc1Sub: 'GOA • LOW',
    sc1Q: 'Is it safe to sail from Panaji Port, Goa tomorrow morning? Inspect waves and wind.',
    sc2Title: 'Rough',
    sc2Sub: 'MUMBAI • HIGH',
    sc2Q: 'Is it safe to venture into the sea from Mumbai Harbour tomorrow at 6 AM?',
    sc3Title: 'Cyclone',
    sc3Sub: 'PARADIP • EXTREME',
    sc3Q: 'Are there active cyclone or high wave warnings near Paradip port, Odisha?',
    sc4Title: 'Fishing Zones',
    sc4Sub: 'KOCHI • PFZ',
    sc4Q: 'Where is the nearest potential fishing zone (PFZ) near Kochi coast today?',
    sc5Title: 'Safe Route',
    sc5Sub: 'MUMBAI • GEOFENCE',
    sc5Q: 'Plot a safe navigational route from Mumbai Harbour avoiding restricted coastal zones.',
  },
  mr: {
    tabToday: 'आढावा',
    tabAsk: 'ORCA ला विचारा',
    tabAuthority: 'प्रशासन',
    tabSystem: 'प्रणाली',
    askTitle: 'ORCA ला विचारा',
    askSub: 'मराठीत विचारा किंवा बोला',
    waves: 'लाटा',
    wind: 'वारा',
    sea: 'समुद्र',
    rain: 'पाऊस',
    vis: 'दृश्यमानता',
    temp: 'तापमान',
    factorTitle: 'घटकांचे योगदान',
    officialWarnings: 'अधिकृत इशारे व सूचना',
    waveHeight: 'लाटांची उंची',
    windSpeed: 'वाऱ्याचा वेग व झोके',
    restrictedZones: 'सीमा व प्रतिबंधित क्षेत्र',
    safeVerdict: 'सफर सुरक्षित आहे',
    dangerVerdict: 'धोका जास्त आहे — जाऊ नका',
    cautionVerdict: 'काळजीपूर्वक जा — किनाऱ्याजवळ रहा',
    safeTip: 'हवामान अनुकूल आहे. VHF चॅनल 16 सुरू ठेवा.',
    dangerTip: 'धोकादायक परिस्थिती आहे. सुधारण्याची शक्यता 11:00 नंतर.',
    cautionTip: 'मध्यम लाटा आहेत. किनाऱ्याजवळ राहा.',
    sugg1: 'दुपारी १२ वाजता काय?',
    sugg1Q: 'दुपारी १२ वाजता समुद्राची परिस्थिती काय असेल?',
    sugg2: 'जवळचे PFZ दाखवा',
    sugg2Q: 'आज सर्वात जवळचे अधिकृत INCOIS मासेमारी क्षेत्र (PFZ) कुठे आहे?',
    sugg3: 'सुरक्षित मार्ग दाखवा',
    sugg3Q: 'प्रतिबंधित क्षेत्रे टाळून सुरक्षित जलमार्ग दाखवा.',
    sugg4: 'चक्रीवादळ इशारा आहे का?',
    sugg4Q: 'जवळपास चक्रीवादळ किंवा वादळी वाऱ्याचा इशारा आहे का?',
    composerPlaceholder: 'काहीही विचारा, बोला किंवा टाईप करा...',
    sc1Title: 'सुरक्षित',
    sc1Sub: 'गोवा • सौम्य',
    sc1Q: 'उद्या सकाळी गोवा (पणजी) बंदरातून समुद्रात जाणे सुरक्षित आहे का?',
    sc2Title: 'खवळलेला',
    sc2Sub: 'मुंबई • धोका',
    sc2Q: 'मी उद्या सकाळी ६ वाजता मुंबईजवळ मासेमारीला जाऊ शकतो का?',
    sc3Title: 'चक्रीवादळ',
    sc3Sub: 'पारादीप • तीव्र',
    sc3Q: 'पारादीप, ओडिशाजवळ चक्रीवादळ किंवा मोठ्या लाटांचा इशारा आहे का?',
    sc4Title: 'मासेमारी क्षेत्र',
    sc4Sub: 'कोची • PFZ',
    sc4Q: 'कोची किनाऱ्याजवळ सर्वात चांगले मासेमारी क्षेत्र कुठे आहे?',
    sc5Title: 'सुरक्षित मार्ग',
    sc5Sub: 'मुंबई • सीमा',
    sc5Q: 'मुंबई बंदरातून प्रतिबंधित क्षेत्र टाळून सुरक्षित मार्ग दाखवा.',
  },
  hi: {
    tabToday: 'अवलोकन',
    tabAsk: 'ORCA से पूछें',
    tabAuthority: 'प्राधिकरण',
    tabSystem: 'प्रणाली',
    askTitle: 'ORCA से पूछें',
    askSub: 'हिंदी में लिखें या बोलें',
    waves: 'लहरें',
    wind: 'हवा',
    sea: 'समुद्र',
    rain: 'बारिश',
    vis: 'दृश्यता',
    temp: 'तापमान',
    factorTitle: 'कारकों का योगदान',
    officialWarnings: 'आधिकारिक चेतावनियां',
    waveHeight: 'लहरों की ऊंचाई',
    windSpeed: 'हवा की गति और झोंके',
    restrictedZones: 'सीमा और प्रतिबंधित क्षेत्र',
    safeVerdict: 'यात्रा सुरक्षित है',
    dangerVerdict: 'खतरा अधिक है — समुद्र में न जाएं',
    cautionVerdict: 'सावधानी बरतें — तट के पास रहें',
    safeTip: 'मौसम अनुकूल है। वीएचएफ चैनल 16 चालू रखें।',
    dangerTip: 'खराब मौसम है। 11:00 के बाद सुधार की संभावना है।',
    cautionTip: 'मध्यम लहरें हैं। सावधानी से आगे बढ़ें।',
    sugg1: 'दोपहर १२ बजे कैसा?',
    sugg1Q: 'आज दोपहर 12 बजे मौसम और समुद्र की स्थिति कैसी रहेगी?',
    sugg2: 'निकटतम PFZ दिखाएं',
    sugg2Q: 'आज सबसे नजदीकी INCOIS मछली पकड़ने का क्षेत्र (PFZ) कहां है?',
    sugg3: 'सुरक्षित मार्ग दिखाएं',
    sugg3Q: 'प्रतिबंधित क्षेत्रों से बचते हुए सुरक्षित समुद्री मार्ग दिखाएं।',
    sugg4: 'तूफान की चेतावनी है?',
    sugg4Q: 'क्या इस क्षेत्र में चक्रवात या तेज आंधी की चेतावनी है?',
    composerPlaceholder: 'कुछ भी पूछें या बोलें...',
    sc1Title: 'सुरक्षित',
    sc1Sub: 'गोवा • शांत',
    sc1Q: 'क्या कल सुबह गोवा तट से समुद्र में जाना सुरक्षित है?',
    sc2Title: 'खराब मौसम',
    sc2Sub: 'मुंबई • चेतावनी',
    sc2Q: 'क्या कल सुबह 6 बजे मुंबई तट पर मछली पकड़ने जा सकते हैं?',
    sc3Title: 'चक्रवात',
    sc3Sub: 'पारादीप • तीव्र',
    sc3Q: 'क्या पारादीप तट के पास चक्रवात या तेज लहरों का अलर्ट है?',
    sc4Title: 'मत्स्य क्षेत्र',
    sc4Sub: 'कोच्चि • PFZ',
    sc4Q: 'कोच्चि के पास निकटतम मछली पकड़ने का क्षेत्र कहां है?',
    sc5Title: 'सुरक्षित मार्ग',
    sc5Sub: 'मुंबई • सीमा',
    sc5Q: 'मुंबई से प्रतिबंधित क्षेत्रों से बचते हुए सुरक्षित मार्ग बनाएं।',
  },
};
