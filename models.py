"""Canonical model identifiers — the single place a model string is written.

CLAUDE.md's rule was "model names live in reviews.py as `_MODEL`", which held
while reviews.py was the only caller. `bedrock_agent.py` added a second one and
hardcoded its own string, which is the same duplication that produced the
Closed/Won and attribution bugs: two copies with nothing keeping them honest.
Both now import from here.

The two identifiers are NOT interchangeable, and neither is a fallback for the
other — they name different models reached over different APIs:

* `LITELLM_MODEL` is a plain Anthropic model id, sent to Okta's LiteLLM proxy
  by `reviews.py`.
* `BEDROCK_MODEL_ID` is an AWS Bedrock *cross-region inference profile* id, sent
  to boto3's `bedrock-runtime` Converse API by `bedrock_agent.py`. The `us.`
  prefix is the geography of the inference profile and is part of the id on that
  API — it is not a typo, and it is not the form the Anthropic SDK's Bedrock
  client would take (that one uses a bare `anthropic.` prefix). Changing the
  region means changing the prefix.
"""

# Sent to the LiteLLM proxy by reviews.py.
LITELLM_MODEL = "claude-sonnet-4-6"

# Sent to bedrock-runtime Converse by bedrock_agent.py. Region-coupled: this
# profile is a US one, matching the region the client is built with.
BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-5"
