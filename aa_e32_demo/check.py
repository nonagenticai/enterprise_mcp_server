from aa_e32_demo.calc import compute_total

got = compute_total(2, 3)
if got != 5:
    raise SystemExit("FAIL: compute_total(2, 3) == %r, expected 5" % (got,))
print("OK: compute_total(2, 3) == 5")
