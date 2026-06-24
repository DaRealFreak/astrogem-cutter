# Test Fixtures

These JSON files are golden vectors emitted by `tools/export_golden.py` from the real
`arkgrid` Python package, which is the source of truth for all decision/probability logic.

## Regenerating

After any change to `arkgrid/` decision or probability logic, regenerate the fixtures and
re-run the TypeScript tests to confirm the TS port still matches:

```bash
source .venv/Scripts/activate
python tools/export_golden.py
cd web && npm test
```
