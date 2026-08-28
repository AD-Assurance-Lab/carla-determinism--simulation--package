"""Hash lock over the frozen rules.

The rules are useless if they can be quietly edited to make a run pass, and a file
cannot be made truly non-editable -- chmod is reversible by whoever is inconvenienced.
What CAN be done is make an edit fail LOUDLY and block the measurement, which is what
this does: the frozen section is hashed, the hash is committed alongside it, and the
preflight refuses until the lock is regenerated through the amendment procedure.
"""
import hashlib
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RULES = HERE / "RULES.md"
LOCK = HERE / "RULES.lock"

START = re.compile(r"^## 2\. Frozen rules\s*$", re.M)
END = re.compile(r"^## 3\. Preflight\s*$", re.M)


def frozen_text():
    src = RULES.read_text(encoding="utf-8")
    m0, m1 = START.search(src), END.search(src)
    if not (m0 and m1):
        raise RuntimeError("RULES.md: frozen section markers not found")
    body = src[m0.start():m1.start()]
    # Normalise trailing whitespace so a stray space cannot break the lock.
    return "\n".join(l.rstrip() for l in body.strip().splitlines()) + "\n"


def digest():
    return hashlib.sha256(frozen_text().encode()).hexdigest()


def write_lock():
    LOCK.write_text(f"{digest()}  RULES.md#frozen-rules\n")
    return digest()


def check_lock():
    if not LOCK.exists():
        return [f"{LOCK.name} is missing"]
    want, got = LOCK.read_text().split()[0], digest()
    if want != got:
        return [f"RULES.md frozen rules were EDITED without an amendment "
                f"(lock {want[:16]}, file {got[:16]}). See RULES.md section 4."]
    return []
