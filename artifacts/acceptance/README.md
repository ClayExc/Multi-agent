# Acceptance artifacts

This directory is reserved for generated, sanitized acceptance evidence.

WP-030 provides the generator in `scripts/acceptance/generate_bundle.py`. Generated
run directories are not release evidence until an independent verifier checks their
declared test/evidence IDs, hashes, run metadata, and secret-scan result.

An empty or zero-case bundle is emitted with `gate_result=fail`,
`report_state=empty`, and no success rate. It must never be presented as a passed
acceptance run or as proof that the 120 functional and 36 safety/fault cases exist.
