"""Real-shaped messages from the communities this bot actually serves.

The groups are Uzbek workers in South Korea. Two kinds of message dominate and
BOTH look like textbook scams to a naive filter:

  - daily work announcements ("there is work tomorrow, 3 people needed,
    130,000 won a day, write to me if you have time")
  - person-to-person currency exchange, won <-> so'm, settled by bank transfer

A moderator that flags those is worse than no moderator: it buries the group's
real purpose in alerts and eventually bans the members who post most usefully.

The discriminator is NOT the topic. It is whether someone is asked to part with
money or credentials up front, on the promise of something later. A job post
that names a wage is ordinary; "pay a 500$ deposit for the visa" is not. An
exchange offer is ordinary; "send yours first and I will send mine after" is
the oldest trick in the book.

Messages are in Uzbek, Russian and English because that is what these groups
actually speak — an English-only ruleset both false-positives on translated
phrasing and misses everything else.
"""

# --- must NEVER be actioned -------------------------------------------------
LEGITIMATE = [
    # work announcements (uz)
    "Assalomu alaykum, ertaga Ansanda ish bor. 3 kishi kerak, kunlik 130.000 won. Vaqti bo'lganlar yozing.",
    "Bugun kechqurun smenaga 2 kishi kerak. Kimda imkon bo'lsa menga yozsin.",
    "Ish bor, zavodda. Kim ishlamoqchi bo'lsa telefon qilsin.",
    "Ertaga ish bormi? Bo'sh kunim bor edi",
    # work announcements (ru)
    "Завтра есть работа в Ансане, нужно 3 человека. 130 тысяч вон за день.",
    "Кто свободен завтра? Есть подработка на складе",
    # currency exchange (uz)
    "Won bor, so'mga almashtiraman. Kurs 1000 won = 10.900 so'm. Bank orqali.",
    "So'm kerak edi, kimda bor? Karta orqali o'tkazaman",
    "Kim won oladi? Naqd yoki bank orqali bo'ladi",
    "Bugungi kurs qancha? So'm almashtirmoqchi edim",
    # currency exchange (ru)
    "Меняю воны на сумы, курс 10900. Перевод по карте",
    "Кому нужны сумы? Есть 5 миллионов, меняю на воны",
    # ordinary chat
    "Assalomu alaykum hammaga, yangi kelganman guruhga",
    "Rahmat, juda foydali ma'lumot",
    "Kimdir Suvon tomonda yashaydimi?",
]

# --- must be caught ---------------------------------------------------------
SCAMS = [
    # advance-fee, dressed as the group's normal business
    "Vizani 2 haftada rasmiylashtiraman, oldindan 500$ to'lash kerak. Kafolat beraman.",
    "Ish topib beraman, faqat oldindan 300$ komissiya. Tez bo'ling, joy kam qoldi.",
    "Avval siz pul o'tkazing, keyin men won yuboraman. Ishoning, men ko'p almashtirganman.",
    # investment
    "Kuniga 10% foyda kafolatlangan. Investitsiya qiling, pul ishlang.",
    "Гарантированный доход 20% в день. Пишите в личку, места ограничены",
    # profile bait / solicitation
    "Mening profilimni ko'ring, sizga yoqadi",
    "check out my profile, you will like what you see",
    # phishing link
    "Pulingizni tekshiring: kb-bank-verify.top/login",
]
