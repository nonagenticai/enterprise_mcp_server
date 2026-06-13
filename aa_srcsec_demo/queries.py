"""AA source-security demo (E3.18) - intentionally vulnerable SQL access layer.

Seeded to exercise the development_source_security_patch card type end-to-end:
the regex/bandit SAST flags the %-formatted query below as a HIGH SQL-injection
finding (CWE-89); the AA pipeline's LLM code-fix worker rewrites it to a
parameterized query and the scanContainerSecurity delta gate proves the drop.
"""


def get_user_by_id(cursor, user_id):
    # INSECURE: SQL string built via %-formatting -> SQL injection (CWE-89)
    cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)
    return cursor.fetchone()
