/* Lightweight interface localization for the English/Hebrew app shell. */
(function () {
    'use strict';

    const STORAGE_KEY = 'rebbe-language';
    const enToHe = {
        'Skip to main content': 'דילוג לתוכן הראשי', 'Conversation navigation': 'ניווט בשיחות',
        'Open conversation navigation': 'פתיחת ניווט השיחות', 'Collapse conversation rail': 'כיווץ סרגל השיחות',
        'New conversation': 'שיחה חדשה', 'Recent conversations': 'שיחות אחרונות',
        'Account': 'חשבון', 'Settings': 'הגדרות', 'Privacy': 'פרטיות', 'Sign out': 'התנתקות', 'Admin': 'ניהול',
        'Shalom, how can I help?': 'שלום, איך אפשר לעזור?',
        'Bring a question about practice, meaning, relationships, or Jewish life. Your answer will distinguish sourced material from model knowledge.': 'אפשר לשאול על מנהגים, משמעות, מערכות יחסים או חיים יהודיים. התשובה תבחין בין מקורות לבין ידע המודל.',
        'Ask a question': 'שאלו שאלה', 'What would you like to explore?': 'על מה תרצו ללמוד?',
        'Enter to send. Shift + Enter for a new line.': 'Enter לשליחה. Shift + Enter לשורה חדשה.',
        'A few places to begin': 'כמה רעיונות להתחלה', 'Curated prompts': 'שאלות מוצעות',
        'Torah': 'תורה', 'Explore a value through sources': 'לימוד ערך דרך מקורות',
        'Shabbat': 'שבת', 'Begin with one meaningful practice': 'מתחילים במנהג משמעותי אחד',
        'Prayer': 'תפילה', 'Find language for a hard moment': 'למצוא מילים לרגע קשה',
        'Guidance': 'הכוונה', 'Think through a personal question': 'לחשוב יחד על שאלה אישית',
        'Weekly learning': 'לימוד שבועי', "This week's Torah portion": 'פרשת השבוע',
        "Read the full d'var Torah": 'קריאת דבר התורה המלא',
        "A short source-aware reflection appears here when this week's edition is available.": 'כאן תופיע מחשבה קצרה המבוססת על מקורות, כשהמהדורה השבועית תהיה זמינה.',
        'Guidance, not psak.': 'הכוונה, לא פסיקת הלכה.', 'A rabbi who knows you personally may counsel differently.': 'רב שמכיר אתכם אישית עשוי לייעץ אחרת.',
        'Source key': 'מקרא מקורות', 'Locally matched': 'נמצא במאגר המקומי',
        'A reference matched to a passage retrieved from the local text library for this answer.': 'הפניה שתואמת לקטע שנמצא בספרייה המקומית עבור תשובה זו.',
        'Model knowledge': 'ידע המודל', 'A citation supplied from model knowledge and not matched against the local library.': 'מקור שהובא מתוך ידע המודל ולא אומת מול הספרייה המקומית.',
        'A human conversation may help': 'ייתכן ששיחה אישית תעזור',
        'This seems like a question where speaking with a rabbi or counselor who knows your situation could be valuable.': 'נראה ששיחה עם רב או יועץ שמכיר את מצבכם עשויה לעזור.',
        'Continue the conversation': 'המשך השיחה', 'Ask a follow-up question': 'שאלת המשך',
        'Settings': 'הגדרות', 'Language': 'שפה', 'Default language': 'שפת ברירת מחדל', 'Default language for your account': 'שפת ברירת המחדל בחשבון',
        'Appearance': 'תצוגה', 'Follow your device or keep a theme for this browser.': 'שימוש בערכת הנושא של המכשיר או בחירה קבועה בדפדפן.',
        'System': 'מערכת', 'system': 'מערכת', 'Light': 'בהיר', 'light': 'בהיר', 'Dark': 'כהה', 'dark': 'כהה', 'Theme preference': 'העדפת ערכת נושא',
        'Theme: system. Activate to change theme.': 'ערכת נושא: מערכת. לחצו לשינוי ערכת הנושא.',
        'Theme: light. Activate to change theme.': 'ערכת נושא: בהירה. לחצו לשינוי ערכת הנושא.',
        'Theme: dark. Activate to change theme.': 'ערכת נושא: כהה. לחצו לשינוי ערכת הנושא.',
        'Account': 'חשבון', 'Credits remaining': 'קרדיטים שנותרו', 'Buy credits': 'רכישת קרדיטים',
        'Each submitted chat message uses one credit.': 'כל הודעה שנשלחת בשיחה משתמשת בקרדיט אחד.',
        'Profile': 'פרופיל', 'Name': 'שם', 'Email': 'דוא״ל', 'Jewish background': 'רקע יהודי',
        'Select...': 'בחירה...', 'Reconstructionist': 'רקונסטרוקציוניסטי', 'Jewish Renewal': 'התחדשות יהודית',
        'Humanistic': 'הומניסטי', 'Reform': 'רפורמי', 'Conservative': 'קונסרבטיבי', 'Orthodox': 'אורתודוקסי',
        'Modern Orthodox': 'אורתודוקסי מודרני', 'Haredi': 'חרדי', 'Hasidic': 'חסידי', 'Litvish/Yeshivish': 'ליטאי/ישיבתי',
        'Open Orthodox': 'אורתודוקסי פתוח', 'Just Jewish': 'יהודי', 'Secular/Cultural': 'חילוני/תרבותי', 'Not Jewish': 'לא יהודי',
        'Your background helps tailor perspective and language.': 'הרקע שלך עוזר להתאים את נקודת המבט ואת השפה.',
        'Context about you': 'קצת עליך', 'Share context that would make guidance more relevant.': 'אפשר לשתף מידע שיעזור להתאים את ההכוונה.',
        'This context is included to personalize your responses.': 'המידע הזה משמש להתאמה אישית של התשובות.',
        'Save profile': 'שמירת הפרופיל', 'Saved': 'נשמר', 'Saving...': 'שומר...', 'Privacy': 'פרטיות',
        'Know where your information goes.': 'חשוב לדעת היכן המידע שלך נשמר.',
        'Read what is stored, how AI and payment providers process data, and how to make a privacy request.': 'מידע על הנתונים שנשמרים, על עיבודם בידי ספקי בינה מלאכותית ותשלומים, ועל בקשות פרטיות.',
        'Read privacy policy': 'קריאת מדיניות הפרטיות', 'Go back': 'חזרה', 'Change theme': 'שינוי ערכת נושא',
        'Send question': 'שליחת שאלה', 'Send follow-up': 'שליחת שאלת המשך', 'Copy': 'העתקה', 'Copied': 'הועתק',
        'Listen': 'האזנה', 'Stop listening': 'עצירת ההאזנה', 'Helpful': 'מועיל', 'Not helpful': 'לא מועיל',
        'Payment successful! Credits have been added to your account.': 'התשלום הצליח! הקרדיטים נוספו לחשבון.',
        'Unlimited': 'ללא הגבלה', 'Error loading': 'שגיאה בטעינה', 'Failed to save profile': 'שמירת הפרופיל נכשלה',
        'Failed to save profile. Please try again.': 'שמירת הפרופיל נכשלה. אפשר לנסות שוב.',
        'Profile saved successfully.': 'הפרופיל נשמר בהצלחה.', 'Profile could not be saved.': 'לא ניתן לשמור את הפרופיל.',
        'Sign in to send your message': 'יש להתחבר כדי לשלוח הודעה',
        'Please sign in to chat with rebbe.dev': 'יש להתחבר כדי לשוחח עם rebbe.dev',
        'Your message is ready to send.': 'ההודעה שלך מוכנה לשליחה.',
        'Dismiss notice': 'סגירת ההודעה', 'Conversation options': 'אפשרויות שיחה',
        'No response received': 'לא התקבלה תשובה', 'Error sending message:': 'שגיאה בשליחת ההודעה:',
        'Request timed out, please try again.': 'הבקשה נמשכה זמן רב מדי. אפשר לנסות שוב.',
        'The request timed out. Please try again.': 'הבקשה נמשכה זמן רב מדי. אפשר לנסות שוב.',
        "I'm having trouble responding right now. Please try again in a moment.": 'קשה לי להשיב כרגע. אפשר לנסות שוב בעוד רגע.',
        'The response could not be completed. Please try again.': 'לא ניתן להשלים את התשובה. אפשר לנסות שוב.',
        'Response complete.': 'התשובה הושלמה.', 'Pastoral': 'הקשבה', 'Listening with an open heart...': 'מקשיב בלב פתוח...',
        'Halachic': 'הלכתי', 'Searching the sources...': 'מחפש במקורות...', 'Moral': 'ערכי',
        'Weighing with care...': 'שוקל בזהירות...', 'Voice': 'ניסוח', 'Crafting a thoughtful response...': 'מנסח תשובה שקולה...',
        'Preparing a response.': 'מכין תשובה.', 'A human rabbi or counselor may be helpful for this question.': 'רב או יועץ אנושי עשוי לעזור בשאלה הזו.',
        'Copy response': 'העתקת התשובה', 'Listen to response': 'האזנה לתשובה', 'Good response': 'תשובה מועילה',
        'Poor response': 'תשובה לא מועילה', 'Copied to clipboard': 'הועתק ללוח', 'Failed to copy': 'ההעתקה נכשלה',
        'Failed to save feedback': 'שמירת המשוב נכשלה', 'Pay Now': 'תשלום עכשיו', 'Processing...': 'מעבד...',
        'Adding credits...': 'מוסיף קרדיטים...', 'Payment received. Credits will be added shortly.': 'התשלום התקבל. הקרדיטים יתווספו בקרוב.',
        'Payment successful. Credits were added.': 'התשלום הצליח. הקרדיטים נוספו.',
        'An unexpected error occurred.': 'אירעה שגיאה בלתי צפויה.', 'Please enter a dedication (e.g. a name).': 'נא להזין הקדשה (למשל שם).',
        'Sponsorship completed successfully.': 'ההקדשה הושלמה בהצלחה.',
        'Preparing a response': 'מכין תשובה', 'Choose a credit package': 'בחירת חבילת קרדיטים',
        'Credit amount': 'כמות קרדיטים', '10 credits': '10 קרדיטים', '25 credits': '25 קרדיטים',
        'Lower cost per credit': 'עלות נמוכה יותר לקרדיט', 'Loading payment form...': 'טוען טופס תשלום...',
        'Pay now': 'תשלום עכשיו', 'Payment handled by Stripe': 'התשלום מטופל באמצעות Stripe',
        'Payment successful. Credits were added.': 'התשלום הצליח. הקרדיטים נוספו.',
        'Payment failed. Please try again.': 'התשלום נכשל. אפשר לנסות שוב.',
        "Sponsor this week's d'var Torah": 'חסות לדבר התורה השבועי',
        "Dedicate this week's Torah learning. Completed dedication text is public. Amounts follow the tradition of giving in multiples of chai, 18.": 'הקדישו את לימוד התורה השבועי. נוסח ההקדשה יפורסם. הסכומים מבוססים על המנהג לתת בכפולות חי (18).',
        'Sponsorship amount': 'סכום החסות', 'Chai': 'חי', 'Double Chai': 'כפל חי', 'Triple Chai': 'פי שלושה חי', 'Tenfold Chai': 'פי עשרה חי',
        'Dedication type': 'סוג ההקדשה', 'In loving memory of...': 'לעילוי נשמת...', 'In honor of...': 'לכבוד...',
        'For a refuah shleima for...': 'לרפואה שלמה עבור...', 'In gratitude for...': 'בהכרת תודה עבור...',
        'Dedicated by...': 'הקדשה מאת...', 'Name or dedication': 'שם או נוסח הקדשה',
        'Continue to payment': 'המשך לתשלום', 'Complete dedication': 'השלמת ההקדשה',
        'Thank you. Your dedication is now part of this week’s learning.': 'תודה. ההקדשה שלך תופיע בלימוד השבוע.',
        'Thank you. Your dedication is now part of this week\'s learning.': 'תודה. ההקדשה שלך תופיע בלימוד השבוע.',
        'Change theme': 'שינוי ערכת נושא', 'Default language': 'שפת ברירת מחדל',
        'rebbe.dev home': 'עמוד הבית של rebbe.dev', 'Expand conversation rail': 'הרחבת סרגל השיחות',
        'Close credit purchase': 'סגירת רכישת הקרדיטים', 'Close sponsorship': 'סגירת חלון ההקדשה',
        'For example, Sarah bat Avraham': 'לדוגמה, שרה בת אברהם', 'Use device language': 'שפת המכשיר',
        'Switch language': 'החלפת שפה', 'Switch language to Hebrew': 'החלפת השפה לעברית', 'Switch language to English': 'החלפת השפה לאנגלית'
    };
    const heToEn = Object.fromEntries(Object.entries(enToHe).map(([en, he]) => [he, en]));

    function detectLanguage() {
        try {
            const saved = localStorage.getItem(STORAGE_KEY);
            if (saved === 'en' || saved === 'he') return saved;
        } catch (_) { /* Continue with browser language. */ }
        const preferred = (navigator.languages || [navigator.language || 'en']).find((value) => /^(he|en)(?:-|$)/i.test(value));
        return preferred && /^he(?:-|$)/i.test(preferred) ? 'he' : 'en';
    }

    let language = detectLanguage();
    const textMap = () => language === 'he' ? enToHe : heToEn;

    function translateNode(node) {
        if (!node || !node.isConnected) return;
        const map = textMap();
        const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
        const textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);
        for (const textNode of textNodes) {
            const trimmed = textNode.nodeValue.trim();
            const translated = map[trimmed];
            if (translated) textNode.nodeValue = textNode.nodeValue.replace(trimmed, translated);
        }
        const elements = node.nodeType === Node.ELEMENT_NODE ? [node, ...node.querySelectorAll('*')] : [];
        for (const element of elements) {
            for (const attr of ['placeholder', 'aria-label', 'title']) {
                const value = element.getAttribute(attr);
                if (value && map[value]) element.setAttribute(attr, map[value]);
            }
        }
    }

    function apply(next, persist) {
        language = next === 'he' ? 'he' : 'en';
        document.documentElement.lang = language;
        document.documentElement.dir = language === 'he' ? 'rtl' : 'ltr';
        document.title = language === 'he' ? 'rebbe.dev | שיחה מונחית' : 'rebbe.dev | Guided conversation';
        if (persist) {
            try { localStorage.setItem(STORAGE_KEY, language); } catch (_) { /* Locale still applies. */ }
        }
        if (document.body) translateNode(document.body);
        const button = document.getElementById('languageToggle');
        if (button) button.setAttribute('aria-label', language === 'he' ? 'החלפת השפה לאנגלית' : 'Switch language to Hebrew');
        document.dispatchEvent(new CustomEvent('rebbe-language-change', { detail: { language } }));
    }

    document.documentElement.lang = language;
    document.documentElement.dir = language === 'he' ? 'rtl' : 'ltr';
    document.addEventListener('DOMContentLoaded', () => {
        apply(language, false);
        const observer = new MutationObserver((records) => {
            for (const record of records) {
                if (record.type === 'childList') record.addedNodes.forEach(translateNode);
                else if (record.type === 'characterData') translateNode(record.target.parentElement);
            }
        });
        observer.observe(document.body, { childList: true, subtree: true, characterData: true });
        document.getElementById('languageToggle')?.addEventListener('click', () => apply(language === 'he' ? 'en' : 'he', true));
    });

    document.addEventListener('rebbe-theme-change', (event) => {
        const button = document.querySelector('[data-theme-cycle]');
        const mode = event.detail?.preference || 'system';
        if (button && language === 'he') {
            const label = mode === 'dark' ? 'כהה' : mode === 'light' ? 'בהירה' : 'מערכת';
            button.setAttribute('aria-label', `ערכת נושא: ${label}. לחצו לשינוי ערכת הנושא.`);
        }
    });

    window.AppI18n = { apply, getLanguage: () => language, storageKey: STORAGE_KEY };
})();
