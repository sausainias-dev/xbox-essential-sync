# Xbox Game Pass full sync — PRO v3.1

This is the corrected version of PRO v3.

Fixes:
- Uses Playwright correctly by evaluating against the Available Games heading element.
- Fixes the JavaScript selector quoting used for `/game/` links.
- Keeps exact source-count validation for Essential, PC, Premium and Ultimate.
- Publishes nothing if any plan count differs from GameScriptions.
- Keeps the four canonical page plans: essential, pc, premium, ultimate.

Run:
```bash
pip install -r requirements.txt
playwright install chromium --with-deps
python sync.py
```
