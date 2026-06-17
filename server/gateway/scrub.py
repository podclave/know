"""Secret-redaction backstop — lifted from podbrain's brain.py SCRUB/scrub().

Defense-in-depth on a SHARED git repo: one leaked credential is everyone's
problem. This runs on every fact body BEFORE it is committed (mandatory), behind
the LLM "no secrets" instruction the secretary/capture prompts carry. Specific
patterns first, broad ones last.
"""
import re

SCRUB = [
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----', re.S), '[REDACTED-PRIVATE-KEY]'),
    (re.compile(r'sk-(?:ant-)?[A-Za-z0-9_-]{12,}'), '[REDACTED]'),          # OpenAI / Anthropic
    (re.compile(r'gh[posru]_[A-Za-z0-9]{20,}'), '[REDACTED]'),              # GitHub (ghp_/gho_/ghs_/ghr_/ghu_)
    (re.compile(r'xox[baprs]-[A-Za-z0-9-]{10,}'), '[REDACTED]'),            # Slack
    (re.compile(r'eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}'), '[REDACTED-JWT]'),  # JWT
    (re.compile(r'\b([a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]+:)[^/\s:@]+(@)'), r'\1[REDACTED]\2'),  # scheme://user:PASS@host
    (re.compile(r'AKIA[0-9A-Z]{16}'), '[REDACTED]'),                        # AWS access key id
    (re.compile(r'([A-Za-z0-9_-]*(?:SECRET|TOKEN|PASSWORD|API_KEY|APIKEY)[A-Za-z0-9_-]*[=:]\s*)[^\s"]+', re.I), r'\1[REDACTED]'),
    (re.compile(r'\b[0-9a-f]{32,}\b'), '[REDACTED]'),                       # generic long hex
]


def scrub(s: str) -> str:
    for rx, rep in SCRUB:
        s = rx.sub(rep, s)
    return s
