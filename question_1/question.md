You recieved untrusted JSON from an LLM. Validate/coerce it to the schema below.

Target schema:
{
    "action": "search" | "answer",
    "q": non-empty str # required iff action == "search"
    "k": int in [1, 5] (default 3) # optional
}

Implement the following method:

from typing import Any, Dict, List, Tuple

def validate_tool_call(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:

"""
Returns (clean, errors). 'clean' strictly follows the schema with defaults applied.
    - Trim strings; coerce numeric strings to ints. 
    - Remove unknown keys.
    - If action == 'answer', ignore 'q' if present (no error).
    - On fatal errors (e.g., missing/invalid 'action', or missing/empty 'q' for search), return ((), errors).
"""