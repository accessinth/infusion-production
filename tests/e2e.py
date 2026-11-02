import json, sys, os, time, shutil, threading, http.server, functools
from playwright.sync_api import sync_playwright
try: sys.stdout.reconfigure(encoding='utf-8')   # ให้พิมพ์ภาษาไทยได้บน Windows console
except Exception: pass

# ทดสอบ index.html (ไฟล์ที่ build แล้ว) ในโหมดทดลอง บน Chrome จริง
# ใช้: cd tests && npm install && pip install playwright && python3 e2e.py
SP = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(SP)
QR = open(os.path.join(SP, 'node_modules/qrcode-generator/qrcode.js'), encoding='utf-8').read()
SBJS = open(os.path.join(SP, 'node_modules/@supabase/supabase-js/dist/umd/supabase.js'), encoding='utf-8').read()
SHOTS = os.path.join(SP, 'shots'); os.makedirs(SHOTS, exist_ok=True)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=APP_DIR)
handler.log_message = lambda *a: None
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8765), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = 'http://127.0.0.1:8765/index.html?demo'   # ?demo บังคับโหมดทดลอง แม้ CONFIG จะชี้ไป Supabase จริงแล้ว

results, errors = [], []
def check(name, ok, info=''):
    results.append(('PASS' if ok else 'FAIL', name, info))

def route(r):
    u = r.request.url
    if 'qrcode-generator' in u: return r.fulfill(status=200, content_type='application/javascript', body=QR)
    if '@supabase/supabase-js' in u: return r.fulfill(status=200, content_type='application/javascript', body=SBJS)
    if u.startswith('http://127.0.0.1'): return r.continue_()
    return r.abort()

with sync_playwright() as p:
    win = [os.path.expandvars(x) for x in (r'%ProgramFiles%\Google\Chrome\Application\chrome.exe',
           r'%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe', r'%LocalAppData%\Google\Chrome\Application\chrome.exe')]
    exe = (os.environ.get('CHROME_PATH') or shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chrome')
           or next((x for x in win if os.path.isfile(x)), None))
    b = p.chromium.launch(executable_path=exe, args=['--no-sandbox']) if exe else p.chromium.launch()
    ctx = b.new_context(viewport={'width':1024,'height':768}, locale='th-TH', timezone_id='Asia/Bangkok')
    ctx.route('**/*', route)
    pg = ctx.new_page()
    pg.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'net::ERR' not in m.text and 'Failed to load resource' not in m.text else None)
    pg.on('pageerror', lambda e: errors.append('PAGEERROR ' + str(e)))
    pg.goto(URL, wait_until='domcontentloaded'); pg.wait_for_selector('.stepbtn', timeout=15000)
    E = lambda js: pg.evaluate(js)

    def pin(name=None, code='1234'):
        pg.wait_for_selector('#modal:not([hidden])', timeout=5000)
        if pg.locator('#modal .who-btn').count():
            pg.locator('#modal .who-btn', has_text=name).first.click()
        for k in code: pg.click(f'#modal [data-m="key"][data-k="{k}"]')
        pg.click('#modal [data-m="ok"]')
        pg.wait_for_selector('#modal', state='hidden', timeout=5000)

    # ---------- โหมดใช้งานจริง (ไม่มี ?demo) ต้องขึ้นหน้าเข้าสู่ระบบ ไม่ใช้ข้อมูลตัวอย่าง ----------
    live = ctx.new_page(); live.on('pageerror', lambda e: errors.append('LIVE PAGEERROR ' + str(e)))
    live.goto(URL.split('?')[0], wait_until='domcontentloaded')
    live.wait_for_selector('form[data-form="login"], .empty', timeout=15000)
    check('ลิงก์หลักใช้ Supabase จริง → ขึ้นหน้าเข้าสู่ระบบ', live.locator('#lg-email').count() == 1 and live.evaluate("S.mode") == 'supabase',
          live.evaluate("S.mode"))
    check('หน้าเข้าสู่ระบบมีทางไปโหมดทดลอง', live.locator('a[href="?demo"]').count() == 1)
    live.close()

    st = E("(() => { const c = {}; for(const p of S.data.pieces){ const s = M.state[p.id]; c[s.status] = (c[s.status]||0)+1 } return c })()")
    check('โหลดแอปและข้อมูลตัวอย่าง', sum(st.values()) > 10, json.dumps(st, ensure_ascii=False))
    check('[hidden] ซ่อนใบงานและหน้าต่าง PIN ตอนเริ่ม', not pg.locator('#sheet').is_visible() and not pg.locator('#modal').is_visible())

    # ---------- หน้างาน: เริ่ม → เสร็จ ----------
    waiting = E("(() => { const c = {}; for(const p of S.data.pieces){ const s = M.state[p.id]; if(s.status==='waiting') (c[s.step] ||= []).push(p.id) } return c })()")
    step = next((s for s in ['S2','S1','S3','S5_1','S6'] if s in waiting), list(waiting)[0])
    pid = waiting[step][0]
    pg.click(f'.stepbtn[data-v="{step}"]')
    check('เลือกจุดงานแล้วเห็นคิว', pg.locator(f'.pcard[data-id="{pid}"]').count() == 1, step)
    pg.click(f'.pcard[data-id="{pid}"]')
    pg.wait_for_selector('[data-act="startStep"]')
    pg.screenshot(path=f'{SHOTS}/01_piece_waiting_1024.png')
    pg.click('[data-act="startStep"]')
    pg.locator('#modal .who-btn').first.wait_for()
    who = pg.locator('#modal .who-btn b').first.inner_text()
    pin(who)
    s1 = E(f"M.state['{pid}']")
    check('กดเริ่มงาน + PIN → สถานะกำลังทำ', s1['status'] == 'working' and s1['step'] == step, f'{who} {step}')
    # แก้ปริมาณวัสดุแถวแรก + เพิ่มแถว
    pg.wait_for_selector('.mat-editor[data-key="log"]')
    rows_before = pg.locator('.mat-editor[data-key="log"] .mrow').count()
    pg.locator('.mat-editor[data-key="log"] .m-qty').first.fill('1.75')
    pg.locator('.mat-editor[data-key="log"] .m-unit').first.select_option(index=0)
    pg.click('[data-act="addMatRow"]')
    rows_after = pg.locator('.mat-editor[data-key="log"] .mrow').count()
    check('เพิ่มแถววัสดุ/ชั้นใยแก้ว', rows_after == rows_before + 1, f'{rows_before}→{rows_after}')
    pg.locator('.mat-editor[data-key="log"] .m-qty').last.fill('500')
    last_unit = pg.locator('.mat-editor[data-key="log"] .m-unit').last
    if last_unit.locator('option[value="g"]').count(): last_unit.select_option('g')
    pg.fill('#logNote', 'ทดสอบบันทึกจริง')
    pg.screenshot(path=f'{SHOTS}/02_piece_working_1024.png', full_page=False)
    pg.click('[data-act="finishStep"]')
    pin(who)
    log = E(f"S.data.step_logs.filter(l => l.piece_id==='{pid}' && l.step==='{step}' && l.status==='done').pop()")
    check('กดบันทึกเสร็จ → บันทึกวัสดุ เวลา หมายเหตุ', log and log['finished_at'] and len(log['materials']) == rows_after and log['note'] == 'ทดสอบบันทึกจริง',
          json.dumps(log['materials'], ensure_ascii=False) if log else 'no log')
    check('แปลงหน่วยกรัม→กก. ถูกต้อง', any(abs(m['qty'] - 0.5) < 1e-9 for m in log['materials']) or any(abs(m['qty'] - 500) < 1e-9 for m in log['materials']), '')
    s2 = E(f"M.state['{pid}']")
    check('ชิ้นงานเลื่อนไปขั้นถัดไป', s2['status'] == 'waiting' and s2['step'] != step, s2.get('step'))

    # ---------- PIN ผิด ----------
    pg.click('[data-act="startStep"]')
    pg.locator('#modal .who-btn').first.click()
    for k in '0000': pg.click(f'#modal [data-m="key"][data-k="{k}"]')
    pg.click('#modal [data-m="ok"]'); pg.wait_for_timeout(300)
    errtxt = pg.locator('#modal .err').inner_text()
    check('PIN ผิดถูกปฏิเสธ', 'ไม่ถูกต้อง' in errtxt and pg.locator('#modal').is_visible(), errtxt)
    pg.click('#modal [data-m="cancel"]')
    check('ยกเลิกหน้าต่าง PIN แล้วงานไม่เปลี่ยน', E(f"M.state['{pid}'].status") == 'waiting')

    # ---------- เริ่มแล้วยกเลิก ----------
    pg.click('[data-act="startStep"]'); pin(who)
    pg.click('[data-act="cancelStep"]'); pin(who)
    check('ยกเลิกการเริ่ม (กดผิด) → กลับไปรอ', E(f"M.state['{pid}'].status") == 'waiting')
    pg.click('.sheet-head [data-act="closeSheet"]')

    # ---------- สแกนรหัส ----------
    code = E(f"M.piece['{pid}'].code")
    pg.fill('#scan', code.lower()); pg.press('#scan', 'Enter')
    pg.wait_for_selector('#sheet:not([hidden])')
    check('สแกน/พิมพ์รหัสเปิดใบงาน', code in pg.locator('.sheet-head h2').inner_text(), code)
    pg.click('.sheet-head [data-act="closeSheet"]')
    pg.fill('#scan', 'XX-NOPE'); pg.press('#scan', 'Enter'); pg.wait_for_timeout(200)
    check('รหัสไม่มีในระบบ → แจ้งเตือน', 'ไม่พบ' in pg.locator('#toast').inner_text())

    # ---------- ผลงานของฉัน ----------
    pg.click('[data-act="myWork"]'); pin(who)
    check('ผลงานของฉัน แสดงเฉพาะของตัวเอง', ('ผลงานของ ' + who) in pg.locator('.sheet-head h2').inner_text())
    pg.click('.sheet-head [data-act="closeSheet"]')

    # ---------- สิทธิ์: ช่างเปิด QC ไม่ได้ ----------
    pg.click('.tab[data-v="qc"]'); pg.wait_for_selector('#modal:not([hidden])')
    names = pg.locator('#modal .who-btn b').all_inner_texts()
    check('แท็บ QC ให้เลือกเฉพาะหัวหน้า/ผู้บริหาร', who not in names and len(names) >= 1, ', '.join(names))
    pin('ประเสริฐ')
    check('ปลดล็อก QC ด้วย PIN หัวหน้า', E("S.view") == 'qc')

    # ---------- QC: ส่งแก้ ----------
    pend = E("qcPending().map(x => ({id:x.piece.id, pt:x.point}))")
    f7 = next((x for x in pend if x['pt'] == 'S7'), None)
    if f7:
        pg.click(f'.pcard[data-id="{f7["id"]}"][data-point="S7"]'); pg.wait_for_selector('#qc-point')
        pg.click('.seg[data-name="qcres"] button[data-v="rework"]')
        pg.click('.seg[data-name="defect"] button[data-v="รอยขัด/ขนแมว"]')
        pg.select_option('#qc-rework', 'S6'); pg.fill('#qc-note', 'ทดสอบส่งแก้')
        pg.screenshot(path=f'{SHOTS}/03_qc_rework_1024.png')
        pg.click('[data-act="saveQC"]'); pg.wait_for_timeout(300)
        s = E(f"M.state['{f7['id']}']")
        check('QC ส่งแก้ → กลับไปทำขั้น 6 ใหม่', s['status'] == 'waiting' and s['step'] == 'S6', s.get('step'))
    else:
        dp = E("S.data.pieces.find(p => M.state[p.id].status==='done').id")
        E(f"openSheet(shPiece, '{dp}')"); pg.click('.sheet-head [data-act="openQC"]'); pg.wait_for_selector('#qc-point')
        pg.select_option('#qc-point', 'S7')
        pg.click('.seg[data-name="qcres"] button[data-v="rework"]')
        pg.click('.seg[data-name="defect"] button[data-v="รอยขัด/ขนแมว"]')
        pg.select_option('#qc-rework', 'S6'); pg.fill('#qc-note', 'ทดสอบส่งแก้')
        pg.screenshot(path=f'{SHOTS}/03_qc_rework_1024.png')
        pg.click('[data-act="saveQC"]'); pg.wait_for_timeout(300)
        s = E(f"M.state['{dp}']")
        check('QC ส่งแก้ (ชิ้นที่เสร็จแล้ว) → กลับไปทำขั้น 6 ใหม่', s['status'] == 'waiting' and s['step'] == 'S6', s.get('step'))
        E(f"openSheet(shPiece, '{dp}')"); pg.click('[data-act="startStep"]'); pin('มานพ')
        pg.locator('.mat-editor[data-key="log"] .m-qty').first.fill('60')
        pg.click('[data-act="finishStep"]'); pin('มานพ')
        E(f"openSheet(shPiece, '{dp}')"); pg.click('[data-act="startStep"]'); pin('สุดา'); pg.click('[data-act="finishStep"]'); pin('สุดา')
        s = E(f"M.state['{dp}']")
        check('ทำขั้น 6–7 ใหม่แล้ว → กลับมารอ QC ขั้นสุดท้าย', s['status'] == 'qc', s['status'])
        pg.click('.sheet-head [data-act="closeSheet"]') if pg.locator('#sheet').is_visible() else None
        nrw = E(f"S.data.step_logs.filter(l => l.piece_id==='{dp}' && l.status==='reworked').length")
        check('งานเดิมที่ถูกสั่งแก้ยังนับในต้นทุน', nrw == 2, f'{nrw} รายการ')
    # ---------- QC: ผ่าน ----------
    pend = E("qcPending().map(x => ({id:x.piece.id, pt:x.point}))")
    if pend:
        x = pend[0]; pg.click(f'.pcard[data-id="{x["id"]}"][data-point="{x["pt"]}"]'); pg.wait_for_selector('#qc-point')
        pg.click('[data-act="saveQC"]'); pg.wait_for_timeout(300)
        check('QC ผ่าน → ออกจากคิวรอตรวจ', not any(y['id'] == x['id'] and y['pt'] == x['pt'] for y in E("qcPending().map(x => ({id:x.piece.id, pt:x.point}))")))
    # ---------- QC: ชิ้นงานเสีย + ชิ้นทดแทน ----------
    victim = E("S.data.pieces.find(p => ['waiting','working'].includes(M.state[p.id].status) && M.state[p.id].done.has('S3')).id")
    n_before = E("S.data.pieces.length")
    E(f"openSheet(shQC, '{victim}', 'S3')")
    pg.click('.seg[data-name="qcres"] button[data-v="scrap"]')
    check('เลือก "ชิ้นงานเสีย" แสดงช่องสร้างชิ้นทดแทน', pg.locator('#qc-replace').is_visible() and not pg.locator('#qc-rework').is_visible())
    pg.click('.seg[data-name="defect"] button[data-v="ฟองอากาศ"]')
    pg.click('[data-act="saveQC"]'); pg.wait_for_timeout(300)
    newp = E("S.data.pieces[S.data.pieces.length-1]")
    check('ชิ้นงานเสีย → สร้างชิ้นทดแทนในออเดอร์เดิม', E(f"M.piece['{victim}'].scrapped") and E("S.data.pieces.length") == n_before + 1 and '-R' in newp['code'], newp['code'])

    # ---------- ออเดอร์ใหม่ ----------
    pg.click('.tab[data-v="orders"]')
    o_before, p_before = E("S.data.orders.length"), E("S.data.pieces.length")
    pg.click('[data-act="newOrder"]'); pg.wait_for_selector('#o-no')
    pg.fill('#o-cust', 'บริษัททดสอบ'); pg.fill('#o-due', '2026-11-20')
    pg.locator('#o-items .i-qty').first.fill('3')
    pg.click('[data-act="addItemRow"]')
    pg.locator('#o-items .i-prod').last.select_option(index=1)
    rt = pg.locator('#o-items .i-route').last.input_value()
    pg.locator('#o-items .i-qty').last.fill('2')
    pg.screenshot(path=f'{SHOTS}/04_order_form_1024.png')
    pg.click('[data-act="saveOrder"]'); pg.wait_for_timeout(300)
    o = E("S.data.orders[S.data.orders.length-1]")
    check('รับออเดอร์ → สร้างชิ้นงานครบจำนวน', E("S.data.orders.length") == o_before + 1 and E("S.data.pieces.length") == p_before + 5, f"{o['order_no']} {o['customer']} ส่ง {o['due_date']}")
    check('เลือกสินค้าแล้วเส้นทางเปลี่ยนตามค่าปกติของสินค้า', rt == E("S.data.products[1].default_route"), rt)
    pg.click('[data-act="openLabels"]'); pg.wait_for_selector('.labels')
    check('ป้าย QR ครบทุกชิ้น', pg.locator('.label svg').count() == 5, str(pg.locator('.label svg').count()))
    check('ปุ่มพิมพ์ป้ายแสดงเมื่อเปิดจากลิงก์ติดตั้งจริง', pg.locator('[data-act="print"]').count() == 1)
    pg.screenshot(path=f'{SHOTS}/05_labels_1024.png')
    pg.click('.sheet-head [data-act="closeSheet"]')
    dup = E("S.data.orders.length")
    pg.click('[data-act="newOrder"]'); pg.fill('#o-no', o['order_no']); pg.click('[data-act="saveOrder"]'); pg.wait_for_timeout(200)
    check('กันเลขที่ออเดอร์ซ้ำ', E("S.data.orders.length") == dup and 'มีอยู่แล้ว' in pg.locator('#toast').inner_text())
    pg.click('.sheet-head [data-act="closeSheet"]')

    # ---------- สต็อก ----------
    pg.click('.tab[data-v="stock"]')
    mid = E("S.data.materials.find(m => m.code==='RS-INF').id")
    before = E(f"stockLevels()['{mid}'].onHand")
    pg.click('[data-act="stockForm"]'); pg.wait_for_selector('#st-mat')
    pg.select_option('#st-mat', mid); pg.fill('#st-qty', '25'); pg.fill('#st-note', 'ทดสอบรับเข้า')
    pg.click('[data-act="saveStock"]'); pg.wait_for_timeout(200)
    after = E(f"stockLevels()['{mid}'].onHand")
    check('รับวัสดุเข้า → ยอดคงเหลือเพิ่ม', abs(after - before - 25) < 1e-6, f'{before:.2f} → {after:.2f} กก.')

    # ---------- ผู้บริหาร ----------
    pg.click('.tab[data-v="dash"]'); pin('ผู้บริหาร')
    check('ปลดล็อกผู้บริหารด้วย PIN', E("S.view") == 'dash')
    kpis = pg.locator('.kpi .v').all_inner_texts()
    check('Dashboard แสดงตัวเลขสรุป', len(kpis) == 5, ' | '.join(kpis))
    pg.click('.seg[data-name="range"] button[data-v="90"]')
    check('เปลี่ยนช่วงเวลา Dashboard', E("S.dashRange") == 90)
    check('ตารางต้นทุนต่อชิ้นมีข้อมูล', pg.locator('text=ต้นทุนจริงต่อชิ้น').count() == 1 and pg.locator('.empty', has_text='ยังไม่มีชิ้นงานที่เสร็จ').count() == 0)
    pg.screenshot(path=f'{SHOTS}/06_dash_1024.png', full_page=True)

    # ---------- ตั้งค่า ----------
    pg.click('.tab[data-v="settings"]')
    wid = E("S.data.workers.find(w => w.name==='สมชาย').id")
    pg.click(f'tr[data-act="editWorker"][data-id="{wid}"]'); pg.wait_for_selector('#w-name')
    pg.fill('#w-pin', '5678'); pg.fill('#w-rate', '72'); pg.click('[data-act="saveWorker"]'); pg.wait_for_timeout(300)
    check('แก้ค่าแรงรายคน', E(f"M.worker['{wid}'].hourly_rate") == 72)
    pg.click('.seg[data-name="settab"] button[data-v="products"]')
    prid = E("S.data.products[0].id")
    pg.click(f'tr[data-act="editProduct"][data-id="{prid}"]'); pg.wait_for_selector('#std-min-S1')
    pg.fill('#std-min-S1', '44'); pg.click('[data-act="saveProduct"]'); pg.wait_for_timeout(300)
    std = E(f"M.product['{prid}'].standard")
    check('แก้สูตรมาตรฐานสินค้า', std['S1']['minutes'] == 44 and len(std['S2']['materials']) >= 3, f"S2 ชั้น {[m.get('layer') for m in std['S2']['materials']]}")
    pg.click('.seg[data-name="settab"] button[data-v="materials"]')
    pg.click('[data-act="editMaterial"]:not([data-id])'); pg.wait_for_selector('#m-code')
    pg.fill('#m-code', 'FB-CB'); pg.fill('#m-name', 'ใยคาร์บอน 200g'); pg.select_option('#m-unit', 'm'); pg.fill('#m-cost', '450')
    pg.click('[data-act="saveMaterial"]'); pg.wait_for_timeout(200)
    check('เพิ่มวัสดุใหม่', E("S.data.materials.some(m => m.code==='FB-CB')"))
    pg.click('.seg[data-name="settab"] button[data-v="general"]'); pg.fill('#g-rate', '75'); pg.click('[data-act="saveGeneral"]'); pg.wait_for_timeout(200)
    check('แก้ค่าแรงกลาง', E("defaultRate()") == 75)

    # ---------- PIN ใหม่ ----------
    pg.click('[data-act="lock"]')
    check('ล็อกแล้วกลับหน้างาน', E("S.view") == 'floor' and E("S.session") is None)
    pg.click('[data-act="myWork"]'); pg.locator('#modal .who-btn', has_text='สมชาย').first.click()
    for k in '1234': pg.click(f'#modal [data-m="key"][data-k="{k}"]')
    pg.click('#modal [data-m="ok"]'); pg.wait_for_timeout(300)
    old_rejected = pg.locator('#modal').is_visible()
    pg.click('#modal [data-m="del"]')
    for k in '5678': pg.click(f'#modal [data-m="key"][data-k="{k}"]')
    pg.click('#modal [data-m="ok"]'); pg.wait_for_selector('#modal', state='hidden')
    check('เปลี่ยน PIN แล้ว PIN เก่าใช้ไม่ได้ PIN ใหม่ใช้ได้', old_rejected and pg.locator('#sheet').is_visible())
    pg.click('.sheet-head [data-act="closeSheet"]')

    # ---------- ข้อมูลอยู่หลังรีโหลด ----------
    counts = E("[S.data.orders.length, S.data.pieces.length, S.data.step_logs.length, S.data.qc_records.length]")
    pg.reload(wait_until='domcontentloaded'); pg.wait_for_selector('.stepbtn')
    check('ปิดเปิดใหม่ ข้อมูลยังอยู่ครบ', E("[S.data.orders.length, S.data.pieces.length, S.data.step_logs.length, S.data.qc_records.length]") == counts, str(counts))

    # ---------- 3 ภาษา (ไทย / เขมร / พม่า) ----------
    E("setLang('th'); S.session=null; S.view='floor'; closeSheet(); render()")
    missing = E("Object.entries(I18N).filter(([k,v]) => !(v[0] && v[1] && v[2])).map(([k]) => k)")
    check('คำแปลครบทุกข้อความ (ไทย/เขมร/พม่า)', not missing, ', '.join(missing[:8]))
    pg.click('.langsw button[data-v="km"]')
    check('ปุ่มสลับภาษา → เขมร', E("document.documentElement.lang") == 'km' and 'បាញ់ជែលកូត' in pg.locator('.stepbar').inner_text())
    check('ใต้ชื่อขั้นตอนมีชื่อไทยกำกับ', 'พ่นเจลโค้ต' in pg.locator('.stepbtn[data-v="S1"]').inner_text())
    pg.click('.langsw button[data-v="my"]')
    check('ปุ่มสลับภาษา → พม่า', E("document.documentElement.lang") == 'my' and 'ဂျယ်လ်ကုတ်ဖျန်း' in pg.locator('.stepbar').inner_text())
    pg.reload(wait_until='domcontentloaded'); pg.wait_for_selector('.stepbtn')
    check('เครื่องจำภาษาล่าสุดหลังรีโหลด', E("S.lang") == 'my' and E("document.documentElement.lang") == 'my')
    pg.click('.langsw button[data-v="th"]')
    # ช่างพม่าเริ่มงาน → หน้าใส่ PIN และทั้งจอเปลี่ยนเป็นภาษาพม่า
    wp2 = E("S.data.pieces.find(p => M.state[p.id].status==='waiting').id")
    E(f"openSheet(shPiece,'{wp2}')"); pg.click('[data-act="startStep"]')
    pg.locator('#modal .who-btn', has_text='มินอ่อง').first.click()
    prompt = pg.locator('#modal').inner_text()
    check('เลือกช่างพม่า → หน้าใส่ PIN เป็นภาษาพม่า', 'PIN ထည့်ပါ' in prompt and E("document.querySelector('#modal').lang") == 'my', prompt.split('\n')[0][:40])
    for k in '0000': pg.click(f'#modal [data-m="key"][data-k="{k}"]')
    pg.click('#modal [data-m="ok"]'); pg.wait_for_timeout(300)
    check('PIN ผิด → ข้อความเตือนเป็นภาษาพม่า', 'PIN မှားသည်' in pg.locator('#modal .err').inner_text())
    for k in '1234': pg.click(f'#modal [data-m="key"][data-k="{k}"]')
    pg.click('#modal [data-m="ok"]'); pg.wait_for_selector('#modal', state='hidden')
    check('ใส่ PIN ถูก → ทั้งจอเป็นภาษาพม่า', E("S.lang") == 'my' and E("document.documentElement.lang") == 'my'
          and E(f"M.state['{wp2}'].status") == 'working')
    check('ใบงานแสดงภาษาพม่า', 'ပြီးကြောင်း မှတ်တမ်းတင်' in pg.locator('#sheetBody').inner_text()
          and 'လုပ်ငန်းခွင်' in pg.locator('#tabs').inner_text())
    # ช่างไทยกดยกเลิก (คนเริ่มเอง=หัวหน้าได้) → กลับเป็นภาษาไทย
    pg.click('[data-act="cancelStep"]'); pg.wait_for_selector('#modal:not([hidden])')
    first_prompt = pg.locator('#modal').inner_text()
    pg.click('#modal [data-m="back"]')                      # เปลี่ยนคน
    pg.locator('#modal .who-btn', has_text='ประเสริฐ').first.click()
    check('กด "เปลี่ยนคน" แล้วเลือกหัวหน้าไทย → หน้าใส่ PIN กลับเป็นไทย', 'ထည့်ပါ' in first_prompt and 'ใส่ PIN ของ' in pg.locator('#modal').inner_text())
    for k in '1234': pg.click(f'#modal [data-m="key"][data-k="{k}"]')
    pg.click('#modal [data-m="ok"]'); pg.wait_for_selector('#modal', state='hidden')
    check('คนถัดไป (หัวหน้าคนไทย) ใส่ PIN → จอกลับเป็นภาษาไทย', E("S.lang") == 'th' and 'ยกเลิกแล้ว' in pg.locator('#toast').inner_text())
    # หน้าผู้บริหาร/ตั้งค่า เป็นไทยเสมอ
    E("setLang('km'); S.session={worker:S.data.workers.find(w=>w.role==='manager'),until:Date.now()+9e6}; closeSheet(); S.view='dash'; render()")
    check('หน้าผู้บริหารยังเป็นภาษาไทยแม้ตั้งภาษาเขมร', 'ภาพรวมการผลิต' in pg.locator('#main').inner_text() and 'ស្តុកសម្ភារៈ' in pg.locator('#tabs').inner_text())
    mon = E("S.data.workers.find(w => w.name.startsWith('มินอ่อง')).id")
    E(f"S.view='settings'; S.setTab='workers'; render(); openSheet(shWorkerForm, '{mon}')")
    check('ฟอร์มช่างเป็นไทย + เลือกภาษาของช่างได้', 'ภาษาบนจอ' in pg.locator('#sheetBody').inner_text() and pg.locator('#w-lang').input_value() == 'my')
    pg.select_option('#w-lang', 'km'); pg.click('[data-act="saveWorker"]'); pg.wait_for_timeout(300)
    check('เปลี่ยนภาษาของช่างแล้วบันทึกได้', E(f"M.worker['{mon}'].lang") == 'km')
    # QC เป็น 3 ภาษา + ตำหนิแปลแต่เก็บค่าเดิม
    E("S.view='qc'; closeSheet(); render()")
    check('หน้า QC เป็นภาษาเขมร', 'រង់ចាំពិនិត្យ' in pg.locator('#main').inner_text())
    qp2 = E("S.data.pieces.find(p => ['waiting','working','qc'].includes(M.state[p.id].status) && M.state[p.id].done.has('S3')).id")
    E(f"openSheet(shQC, '{qp2}', 'S3')")
    pg.click('.seg[data-name="qcres"] button[data-v="rework"]')
    check('ปุ่มตำหนิแสดงภาษาเขมร', 'ពពុះខ្យល់' in pg.locator('.seg[data-name="defect"]').inner_text())
    pg.click('.seg[data-name="defect"] button[data-v="ฟองอากาศ"]'); pg.select_option('#qc-rework', 'S3')
    pg.click('[data-act="saveQC"]'); pg.wait_for_timeout(300)
    check('บันทึกตำหนิเป็นค่ากลาง (ไทย) ในฐานข้อมูล', E(f"S.data.qc_records.filter(q => q.piece_id==='{qp2}').pop().defect") == 'ฟองอากาศ')
    # จอแคบ 390px ภาษาเขมร/พม่าไม่ล้น
    pw = lambda: E("Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth, document.querySelector('#sheet').hidden ? 0 : document.querySelector('.sheet-panel').scrollWidth - document.querySelector('.sheet-panel').clientWidth)")
    pg.set_viewport_size({'width':390, 'height':844})
    for lang in ['km', 'my']:
        E(f"setLang('{lang}'); S.view='floor'; closeSheet(); render()"); pg.wait_for_timeout(100); o_floor = pw()
        E("openSheet(shPiece, S.data.pieces.find(p => M.state[p.id].status==='working').id)"); pg.wait_for_timeout(100); o_piece = pw()
        if lang == 'my': pg.screenshot(path=f'{SHOTS}/11_phone_my_piece.png')
        E("closeSheet(); S.view='qc'; render()"); pg.wait_for_timeout(100); o_qc = pw()
        E(f"openSheet(shMyWork, S.data.workers[0].id)"); pg.wait_for_timeout(100); o_my = pw()
        if lang == 'km': pg.screenshot(path=f'{SHOTS}/12_phone_km_mywork.png')
        E("closeSheet(); S.view='floor'; render()")
        if lang == 'my': pg.screenshot(path=f'{SHOTS}/13_phone_my_floor.png')
        check(f'จอ 390px ไม่ล้น ({lang})', max(o_floor, o_piece, o_qc, o_my) <= 0, f'หน้างาน {o_floor} ใบงาน {o_piece} QC {o_qc} ผลงาน {o_my}')
    pg.set_viewport_size({'width':1024, 'height':768})
    E("setLang('th'); S.session=null; S.view='floor'; closeSheet(); render()")

    # ---------- ขนาดจอ / ล้นจอ ----------
    def overflow(): return E("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    for vw, vh, tag in [(1024,768,'tablet-land'), (768,1024,'tablet-port'), (390,844,'phone')]:
        pg.set_viewport_size({'width':vw, 'height':vh}); pg.wait_for_timeout(150)
        E("S.view='floor'; closeSheet(); render()")
        o1 = overflow()
        E("openSheet(shPiece, S.data.pieces.find(p => M.state[p.id].status==='waiting').id)"); pg.wait_for_timeout(100)
        o2 = E("document.querySelector('.sheet-panel').scrollWidth - document.querySelector('.sheet-panel').clientWidth")
        if tag == 'phone': pg.screenshot(path=f'{SHOTS}/07_phone_piece.png')
        E("closeSheet(); S.session={worker:S.data.workers.find(w=>w.role==='manager'),until:Date.now()+9e6}; S.view='dash'; render()")
        o3 = overflow()
        E("S.view='settings'; S.setTab='products'; render(); openSheet(shProductForm, S.data.products[0].id)"); pg.wait_for_timeout(100)
        o4 = E("document.querySelector('.sheet-panel').scrollWidth - document.querySelector('.sheet-panel').clientWidth")
        if tag == 'phone': pg.screenshot(path=f'{SHOTS}/08_phone_product.png')
        E("closeSheet(); S.view='floor'; render()")
        if tag == 'phone': pg.screenshot(path=f'{SHOTS}/09_phone_floor.png')
        check(f'ไม่ล้นจอแนวนอน ({tag} {vw}px)', max(o1,o2,o3,o4) <= 0, f'หน้างาน {o1} ใบงาน {o2} dashboard {o3} สูตร {o4}')
    pg.set_viewport_size({'width':1024,'height':768})
    pg.emulate_media(color_scheme='dark'); E("S.view='floor'; render()"); pg.wait_for_timeout(150)
    pg.screenshot(path=f'{SHOTS}/10_dark_floor.png')
    check('ไม่มี error ใน console', not errors, ' | '.join(errors[:5]))
    b.close()
srv.shutdown()
for r in results: print(*r, sep='\t')
print('TOTAL', sum(r[0]=='PASS' for r in results), '/', len(results))
sys.exit(0 if all(r[0]=='PASS' for r in results) else 1)
