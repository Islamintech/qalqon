"""Flags dangerous files. This is a DETECTOR, not anything that touches the
file's contents — it decides on the declared name, type and size only.

Two uses:
  - files posted directly in the group (the bot sees these already), e.g. a
    scammer dropping a fake 'wallet.apk'
  - files found in a linked channel once fetched via MTProto (phase 2b)
"""
from .verdict import Verdict, Risk

# Executable / installer types that have no business being shared to strangers.
DANGEROUS_EXTENSIONS = {
    ".apk", ".apks", ".xapk", ".exe", ".msi", ".scr", ".bat",
    ".cmd", ".com", ".jar", ".vbs", ".ps1", ".sh", ".dmg",
}

# Words common in malware/scam file names.
SUSPICIOUS_NAME_HINTS = [
    "crack", "keygen", "mod", "hack", "cheat", "free", "premium",
    "wallet", "airdrop", "verify", "update-now", "giveaway",
]


class FileScanner:
    def scan(
        self,
        file_name: str,
        mime_type: str | None = None,
        file_size: int | None = None,
    ) -> Verdict:
        name = (file_name or "").lower()
        ext = f".{name.rsplit('.', 1)[-1]}" if "." in name else ""
        reasons: list[str] = []
        risk = Risk.CLEAN

        if ext in DANGEROUS_EXTENSIONS:
            reasons.append(f"dangerous file type {ext}")
            risk = Risk.RED_FLAG

        # A dangerous extension that is NOT the final one — "wallet.apk.txt",
        # "invoice.exe.pdf" — is a disguise, not an accident. The file will not
        # execute as-is, so this is a hint rather than proof: either someone is
        # hiding what they sent, or a real payload is one rename away.
        segments = name.split(".")[1:-1]
        buried = [f".{seg}" for seg in segments if f".{seg}" in DANGEROUS_EXTENSIONS]
        if buried:
            reasons.append(f"disguised double extension {buried[0]} inside the name")
            if risk is Risk.CLEAN:
                risk = Risk.FIFTY_FIFTY

        for hint in SUSPICIOUS_NAME_HINTS:
            if hint in name:
                reasons.append(f"suspicious name term '{hint}'")
                if risk is Risk.CLEAN:
                    risk = Risk.FIFTY_FIFTY

        # An .apk sent as a generic/octet-stream mime is a classic disguise.
        if ext == ".apk" and mime_type and "android" not in mime_type:
            reasons.append(f"apk with mismatched mime '{mime_type}'")
            risk = Risk.RED_FLAG

        # The filename goes in the reason: a reviewer cannot judge
        # "suspicious name term 'wallet'" without knowing what the file was
        # actually called, and a mismatch between what the sender claims and
        # what the extension says is often the whole story.
        detail = "; ".join(reasons) or "file looks ok"
        return Verdict(
            risk=risk,
            reason=f"'{file_name}' — {detail}" if file_name else detail,
            source="file",
        )

    def scan_attachment(self, msg) -> Verdict:
        """Scan whatever file a Telegram message carries.

        Documents are the obvious case, but a scammer can send the same payload
        as an animation/video/audio and the old document-only handler let it
        through. Telegram itself only guarantees the DECLARED name and mime, so
        a missing name is not evidence of anything — we just have less to go on.
        """
        for attr in ("document", "animation", "video", "audio", "voice", "video_note"):
            obj = getattr(msg, attr, None)
            if obj is None:
                continue
            name = getattr(obj, "file_name", None) or ""
            mime = getattr(obj, "mime_type", None)
            size = getattr(obj, "file_size", None)
            if not name and not mime:
                continue
            verdict = self.scan(name, mime, size)
            if not verdict.clean:
                return verdict
        return Verdict(Risk.CLEAN, "no dangerous attachment", "file")
