"""สร้าง index.html (ไฟล์ที่ขึ้น GitHub Pages) จาก src/app.html
src/app.html คือต้นฉบับ แก้ที่ไฟล์นั้นเท่านั้น แล้วรัน: python3 build.py
src/app.html ไม่มี <!doctype>/<head>/<body> เพื่อให้ publish เป็น claude.ai artifact ได้ด้วย
build จึงเติม doctype, charset, viewport ให้ ถ้าขาด viewport ตัวหนังสือบนแท็บเล็ตจะเล็กมาก
"""
from pathlib import Path
root = Path(__file__).parent
src = (root / 'src' / 'app.html').read_text(encoding='utf-8')
cut = src.index('</style>') + len('</style>')
head, body = src[:cut], src[cut:]
out = f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<style>:root{{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}}</style>
{head}
</head>
<body>{body}
</body>
</html>
"""
(root / 'index.html').write_text(out, encoding='utf-8')
print('built index.html', len(out), 'bytes')
