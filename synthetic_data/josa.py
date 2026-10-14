"""한국어 조사 선택(받침 유무)."""
_DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}


def _last_batchim(word: str):
    for ch in reversed(word.rstrip()):
        if "가" <= ch <= "힣":
            return (ord(ch) - 0xAC00) % 28
        if ch in _DIGIT_BATCHIM:
            return {"0": 21, "1": 8, "3": 16, "6": 1, "7": 8, "8": 8}.get(ch, 0)
        if ch.isalnum():
            return 0
    return 0


def has_batchim(word: str) -> bool:
    return _last_batchim(word) != 0


def i_ga(word: str) -> str:
    return word + ("이" if has_batchim(word) else "가")


def eun_neun(word: str) -> str:
    return word + ("은" if has_batchim(word) else "는")


def eul_reul(word: str) -> str:
    return word + ("을" if has_batchim(word) else "를")


def euro(word: str) -> str:
    b = _last_batchim(word)
    return word + ("로" if b in (0, 8) else "으로")
