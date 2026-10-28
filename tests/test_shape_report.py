

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

from src.validate_upload import (
    EMAIL_SHAPE,
    shape_findings,
    shape_report,
)

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"[ok] {name}")
    else:
        failures.append(f"{name}: {detail}")
        print(f"[FAIL] {name} {detail}")


good = ["maria.day697@hotmail.com", "a@b.c"]
bad = ["budi@", "@gmail.com", "budi", "budi@@gmail.com", "budi gmail.com",
       "not an email", "", "x.y@z"]
check("email accepts real addresses",
      all(EMAIL_SHAPE.match(v) for v in good), str(good))
check("email rejects malformed",
      not any(EMAIL_SHAPE.match(v) for v in bad), str(bad))

df = pd.DataFrame({
    "email": ["a@b.com", "budi@", "", None, "  "],
    "phone_number": ["449.977.1729x282", "N/A", "", None, "021-abc"],
    "dob": ["11/04/1988", "not a date", "", None, "25/03/1955"],
    "customer_pk": [1, 2, 3, 4, 5],
})
rep = shape_report(df, date_evidence={"dob": {"applied_order": "dmy"}})

em = rep["email"]
check("email: 2 non-blank counted (blanks excluded)", em["non_blank"] == 2, str(em))
check("email: 3 blank not counted as failures", em["blank"] == 3, str(em))
check("email: only 'budi@' malformed", em["unshaped"] == 1 and em["samples"] == ["budi@"],
      f"unshaped={em['unshaped']} samples={em['samples']}")

ph = rep["phone"]
check("phone: 'N/A' fails (no digits)", ph["unshaped"] == 1 and ph["samples"] == ["N/A"],
      f"unshaped={ph['unshaped']} samples={ph['samples']}")
check("phone: '021-abc' does not fail (yields '021')",
      "021-abc" not in ph["samples"], str(ph["samples"]))
check("phone: extension 'x282' does not fail", "449.977.1729x282" not in ph["samples"],
      str(ph["samples"]))

dob = rep["dob"]
check("dob: 3 non-blank (blanks excluded)", dob["non_blank"] == 3, str(dob))
check("dob: 'not a date' is the only failure", dob["unshaped"] == 1
      and dob["samples"] == ["not a date"], f"unshaped={dob['unshaped']} samples={dob['samples']}")

# --- 3. unresolved date order => measurable False, never reported as failure ---
rep_unres = shape_report(df, date_evidence={"dob": {"applied_order": None}})
check("dob: unresolved order marked not measurable",
      rep_unres["dob"].get("measurable") is False, str(rep_unres["dob"]))

df_wrong_map = pd.DataFrame({"email": ["not-an-email", "nope", "hmm", "xyz", "abc"]})
b, w = shape_findings(shape_report(df_wrong_map))
check("all-bad email blocks",
      any("does not parse as a valid email address in ANY" in x for x in b),
      f"blocking={b}")
check("all-bad email produces no recall-style warning",
      not any("do not parse as a valid email" in x for x in w), f"warnings={w}")

# partial failure => warning, NOT blocking (no invented threshold)
df_partial = pd.DataFrame({"email": ["a@b.com"] * 9 + ["budi@"]})
b, w = shape_findings(shape_report(df_partial))
check("partial malformed email warns, does not block",
      not b and any("do not parse as a valid email" in x for x in w), f"b={b} w={w}")

df_blank = pd.DataFrame({"email": ["", None, "   "]})
b, w = shape_findings(shape_report(df_blank))
check("blank-only column produces no shape finding", not b and not w, f"b={b} w={w}")

dup_pk = pd.DataFrame({"email": ["a@b.com"], "customer_pk": [7]})
b, w = shape_findings(shape_report(dup_pk))
check("unique pk does not block", not b, str(b))

dup_pk2 = pd.DataFrame({"email": ["a@b.com", "c@d.com"], "customer_pk": [7, 7]})
b, w = shape_findings(shape_report(dup_pk2))
check("duplicate pk blocks", any("duplicated value(s)" in x for x in b), f"b={b}")

no_pk = pd.DataFrame({"email": ["a@b.com"]})
check("absent customer_pk column not reported", "customer_pk" not in shape_report(no_pk),
      str(shape_report(no_pk).keys()))

print()
if failures:
    print(f"FAIL — {len(failures)} assertion(s):")
    for f in failures:
        print(f" - {f}")
    raise SystemExit(1)
print("PASS")
