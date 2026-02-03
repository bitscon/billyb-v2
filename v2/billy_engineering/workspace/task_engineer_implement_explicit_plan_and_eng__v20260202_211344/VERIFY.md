What was verified
- That documentation and charter language now use explicit /plan and /engineer modes.
- That /engineer is the only engineering trigger via a unit test.
- That CLI help text documents /plan and /engineer usage.

How it was verified
- Manual inspection of updated files.
- Added unit test to assert detect_engineering_intent only returns true for /engineer.

What was not verified
- Runtime end-to-end behavior with a live LLM provider.
- Full charter reload behavior in production.
- No automated tests were executed in this step.

Pass/Fail
- Pass (based on manual inspection and added test).
