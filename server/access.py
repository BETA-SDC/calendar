"""Shared organization access checks for HTTP requests and publication jobs."""
import time


def organization_access(connection, user_id):
    now = int(time.time())
    owner = connection.execute(
        "SELECT 1 FROM github_admin_grants a JOIN github_accounts g ON g.user_id=a.user_id "
        "WHERE a.user_id=? AND a.valid_until>?",
        (user_id, now),
    ).fetchone() is not None
    member = connection.execute(
        "SELECT 1 FROM group_members m JOIN account_groups g ON g.id=m.group_id "
        "JOIN github_accounts a ON a.user_id=m.user_id "
        "WHERE m.user_id=? AND m.source='github' AND g.external_key=? AND g.archived=0 "
        "AND (m.valid_until IS NULL OR m.valid_until>?)",
        (user_id, "github:org:BETA-SDC", now),
    ).fetchone() is not None
    return {"role": "owner" if owner else "member" if member else "viewer",
            "member": member or owner, "owner": owner}
