import re


def normalize_phone_to_e164_il(raw_phone: str) -> str:
    """
    Normalize Israeli phone numbers to E.164 (+972) format.

    Rules:
    - Strip spaces, dashes, parentheses, and the 'whatsapp:' prefix if present.
    - If the number already starts with '+', return it as-is (assume it is already E.164).
    - If it starts with '0' and has 10 digits (e.g. '0501234567'):
        -> remove the leading '0' and prefix with '+972' -> '+972501234567'.
    - If it starts with '5' and has 9 digits (e.g. '501234567'):
        -> prefix with '+972' -> '+972501234567'.
    - If nothing matches, return the cleaned input.
    """
    if not raw_phone:
        return raw_phone

    phone = raw_phone.strip()
    phone = phone.replace("whatsapp:", "")
    phone = re.sub(r"[()\s-]+", "", phone)

    if phone.startswith("+"):
        return phone

    if phone.startswith("0") and len(phone) == 10:
        return "+972" + phone[1:]

    if phone.startswith("5") and len(phone) == 9:
        return "+972" + phone

    return phone
