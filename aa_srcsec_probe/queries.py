"""AA source-security probe fixture. See aa_srcsec_probe/README.md.

WHAT THIS CODE DOES TODAY: a single read helper that looks a user row up by id
against a DB-API cursor. The SQL sent to the cursor is assembled by applying the
%-format operator to the query string before it is passed to execute().

The acceptance oracle for this package is check_srcsec.py. It pins the
behaviour any change here must preserve; it does not prescribe the change.
Run it with:  python -m aa_srcsec_probe.check_srcsec
"""


def get_user_by_id(cursor, user_id):
    """Return the users row whose id is `user_id`, or None if there is none."""
    cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)
    return cursor.fetchone()
