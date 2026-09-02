# Bot profile assets

Everything BotFather asks for, and which field each piece belongs to. Run
`/mybots` -> @QalqonSafeBot -> Edit Bot.

| BotFather field | Command | This repo | Size |
|---|---|---|---|
| Botpic (round avatar) | `/setuserpic` | `botpic-avatar.png` | 512x512 |
| Description Picture (start page) | `/setdescriptionpic` | `botpic-uz.png` | 640x360 |
| About | `/setabouttext` | below, 120 char max | — |
| Description | `/setdescription` | below, 512 char max | — |
| Commands | `/setcommands` | below | — |
| Privacy Policy | Edit Privacy Policy | `<WEB_BASE_URL>/privacy` | — |

`botpic-en.png` is the English-tagline variant of the start page image.

**Botpic and Description Picture are not the same thing.** The avatar is
cropped to a circle, so it is a separate square image carrying the mark alone
— the 640x360 one scaled down would centre-crop to a slice of the wordmark.

## About (120 max)

```
Guruhlarni firibgarlik va spamdan himoya qiladi. Shubhalini o'chiradi, qolganini adminga yuboradi.
```

## Description (512 max)

```
Qalqon — guruhingizni firibgarlardan himoya qiluvchi moderator bot.

Har bir xabarni oltita mustaqil signal tekshiradi: kalit so'zlar, havolalar, fayllar, yozish tezligi, profil va til modeli. Aniq hujum o'chiriladi, shubhali holat esa adminga yuboriladi — qaror odamniki.

Oddiy suhbat saqlanmaydi. Bot faqat chora ko'rilgan holatlarni yozib qo'yadi.

Ishga tushirish: botni guruhga qo'shing va admin qiling.
```

## Commands

Paste the whole block in one message. These mirror `controllers/admin_controller.HELP`
— change one, change the other, or the autocomplete starts lying.

```
stats - Ushbu guruh bo'yicha umumiy ma'lumot
status - Foydalanuvchi yozuvi va so'nggi holatlar
whitelist - Foydalanuvchiga ishonish, ogohlantirishlarni tozalash
unwhitelist - Ishonchni bekor qilish
forgive - Faol ogohlantirishlarni tozalash
unban - Blokni ochish
dryrun - Xavfsizlik kalitini ko'rish yoki o'zgartirish
digest - Kutilayotgan hisobotni hozir yuborish
help - Buyruqlar ro'yxati
```

## Regenerating

```bash
pip install playwright && playwright install chromium
python deploy/branding/generate.py
```

The images are drawn from `web.render.SHIELD`, the same path data behind the
favicon and the site header, so the three can never drift apart. Playwright is
deliberately not in `requirements-dev.txt`: this runs by hand when the mark
changes, not on every build.
