# Relay Command

IMMEDIATELY execute the following without deliberation:

**If $ARGUMENTS is empty:**
1. Call `relay_fetch(limit=5, reader="code")`
2. Find the most recent message from sender "desktop"
3. Execute those instructions

**If $ARGUMENTS is not empty:**
Call `relay_send(message="$ARGUMENTS", sender="code")` immediately.

## Arguments
$ARGUMENTS
