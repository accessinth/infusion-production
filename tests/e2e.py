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

    # ---------- ตรวจความเสี่ยง (2 พ.ย.): เวลาซ้อน, หลายเครื่อง, สถานะ, ร่าง, การดึงข้อมูล ----------
    E("setLang('th'); S.session=null; S.view='floor'; closeSheet(); render()")
    AW = "askWorker = async (o) => (o && o.preselect) ? S.data.workers.find(w => w.id===o.preselect) : S.data.workers.find(w => w.role==='worker' && (w.lang||'th')==='th'); 0"
    E("window.__aw = askWorker; 0"); E(AW)
    alloc = E("""(() => { const w = S.data.workers.find(x => x.role==='worker').id, base = Date.parse('2026-01-05T08:00:00Z'), m = 60000;
      const mk = (a, b) => ({id:uid(), worker_id:w, finished_by:w, started_at:new Date(base+a*m).toISOString(), finished_at:new Date(base+b*m).toISOString(), status:'done'});
      const same = [mk(0,60), mk(0,60), mk(0,60)], part = [mk(0,60), mk(30,90)], seq = [mk(0,30), mk(30,60)];
      const r1 = allocateWork(same), r2 = allocateWork(part), r3 = allocateWork(seq);
      return {same: same.map(l => Math.round(r1[l.id])), part: part.map(l => Math.round(r2[l.id])), seq: seq.map(l => Math.round(r3[l.id]))} })()""")
    check('ช่างทำ 3 ชิ้นพร้อมกัน 60 นาที → ชิ้นละ 20 นาที (รวม 60 ไม่นับซ้ำ)', alloc['same'] == [20, 20, 20], str(alloc['same']))
    check('ทำซ้อนกันบางช่วง (0–60, 30–90) → 45 + 45 = 90 นาที', alloc['part'] == [45, 45], str(alloc['part']))
    check('ทำต่อกันไม่ซ้อน → นับเต็มแต่ละชิ้น', alloc['seq'] == [30, 30], str(alloc['seq']))
    check('ดึงข้อมูลแบบแบ่งหน้ามีการเรียงลำดับ (กันแถวซ้ำ/หายเมื่อเกิน 1000)', '.order(' in E("fetchAll.toString()"))
    # อีกเครื่องยกเลิกไปแล้ว แต่เครื่องนี้ยังกดบันทึกเสร็จจากจอเก่า
    sp = E("S.data.pieces.find(p => M.state[p.id].status==='waiting' && ['S1','S3'].includes(M.state[p.id].step)).id")
    E(f"openSheet(shPiece,'{sp}')"); pg.click('[data-act="startStep"]'); pg.wait_for_timeout(300)
    slid = E(f"M.state['{sp}'].log.id")
    E(f"(() => {{ const l = S.data.step_logs.find(x => x.id==='{slid}'); l.status='cancelled'; l.finished_at=new Date().toISOString(); }})()")
    pg.click('[data-act="finishStep"]'); pg.wait_for_timeout(300)
    check('อีกเครื่องยกเลิกงานแล้ว เครื่องนี้กดบันทึกเสร็จ → ไม่ทับ + แจ้งเตือน', E(f"S.data.step_logs.find(x => x.id==='{slid}').status") == 'cancelled'
          and 'อีกเครื่อง' in pg.locator('#toast').inner_text(), pg.locator('#toast').inner_text())
    # ร่างที่พิมพ์ค้างไว้รอดการรีเฟรช
    dp = E("S.data.pieces.find(p => M.state[p.id].status==='waiting' && ['S1','S3'].includes(M.state[p.id].step)).id")
    E(f"openSheet(shPiece,'{dp}')"); pg.click('[data-act="startStep"]'); pg.wait_for_timeout(300)
    dlid = E(f"M.state['{dp}'].log.id")
    pg.locator('.mat-editor[data-key="log"] .m-qty').first.fill('7.25'); pg.fill('#logNote', 'ร่างทดสอบ')
    pg.reload(wait_until='domcontentloaded'); pg.wait_for_selector('.stepbtn'); E("window.__aw = askWorker; 0"); E(AW)
    E(f"openSheet(shPiece,'{dp}')")
    check('รีเฟรชระหว่างกรอก → ตัวเลขและหมายเหตุที่พิมพ์ค้างไว้กลับมา', pg.locator('.mat-editor[data-key="log"] .m-qty').first.input_value() == '7.25'
          and pg.input_value('#logNote') == 'ร่างทดสอบ' and pg.locator('[data-draft] .chip.info').count() == 1)
    pg.click('[data-act="finishStep"]'); pg.wait_for_timeout(300)
    check('บันทึกเสร็จแล้วล้างร่าง + เก็บค่าตามที่พิมพ์', E(f"localStorage.getItem('mi:draft:{dlid}')") is None
          and E(f"S.data.step_logs.find(x => x.id==='{dlid}').note") == 'ร่างทดสอบ')
    # QC สั่งแก้ย้อนหลังขณะขั้นถัดไปกำลังทำ / ตีเสียขณะกำลังทำ
    E("S.session={worker:S.data.workers.find(w=>w.role==='supervisor'),until:Date.now()+9e6}; closeSheet(); render()")
    rp = E("S.data.pieces.find(p => M.state[p.id].status==='waiting' && M.state[p.id].done.has('S3') && M.state[p.id].step!=='S3')?.id")
    E(f"openSheet(shPiece,'{rp}')"); pg.click('[data-act="startStep"]'); pg.wait_for_timeout(300)
    E(f"openSheet(shQC,'{rp}','S3')"); pg.click('.seg[data-name="qcres"] button[data-v="rework"]')
    pg.click('.seg[data-name="defect"] button >> nth=0'); pg.select_option('#qc-rework', 'S3'); pg.click('[data-act="saveQC"]'); pg.wait_for_timeout(300)
    check('QC สั่งแก้ขั้น 3 ขณะขั้นถัดไปกำลังทำ → ปิดงานค้าง และชิ้นงานกลับไปขั้น 3',
          E(f"S.data.step_logs.filter(l => l.piece_id==='{rp}' && l.status==='in_progress').length") == 0 and E(f"[M.state['{rp}'].status, M.state['{rp}'].step]") == ['waiting', 'S3'])
    xp = E("S.data.pieces.find(p => M.state[p.id].status==='working')?.id")
    E(f"openSheet(shQC,'{xp}','S3')"); pg.click('.seg[data-name="qcres"] button[data-v="scrap"]')
    pg.click('.seg[data-name="defect"] button >> nth=0'); pg.click('[data-act="saveQC"]'); pg.wait_for_timeout(300)
    check('ตีชิ้นงานเสียขณะมีคนกำลังทำ → ไม่มีงานค้าง "กำลังทำ"', E(f"S.data.step_logs.filter(l => l.piece_id==='{xp}' && l.status==='in_progress').length") == 0)
    E("askWorker = window.__aw; S.session=null; S.view='floor'; closeSheet(); render(); 0")

    # ---------- งานเรือ 4 แบบ (ขั้นตอนการผลิตเรือ) ----------
    E("setLang('th'); S.session=null; S.view='floor'; closeSheet(); render()")
    rd = E("Object.fromEntries(['JB','JW','CP','CF'].map(r => [r, routeSteps(r, true).map(k => STEPS[k].name)]))")
    check('JelCode ดำ/ขาว 12 ขั้น ตามลำดับ (QC ไม่นับเป็นขั้น)', rd['JB'] == rd['JW'] == ['ทาน้ำยาถอดแบบ','พ่นเจลโค้ต','ปูใยแก้ว','อินฟิวชั่น','แกะออกจากแม่พิมพ์','เจียรตัดแต่ง','ประกบชิ้นงาน','พ่นเรซินเจลโค้ต','ขัดเก็บผิว','ขัดเงา','ล้าง เตรียมส่ง','ห่องานพร้อมส่ง'], ' → '.join(rd['JB']))
    check('สีตามลูกค้า: โป๊ว → ขัด → สีพื้น → สีลูกค้า → แล็คเกอร์ → ขัดเงา → ห่อ', rd['CP'][6:] == ['ประกบชิ้นงาน','โป๊วเก็บงาน','ขัดเก็บผิว','พ่นสีพื้น','พ่นสีตามลูกค้าสั่ง','พ่นเคลือบแล็คเกอร์','ขัดเงา','ห่องานพร้อมส่ง'], ' → '.join(rd['CP']))
    check('Carbon: ปูผ้า Prepreg → เข้าตู้อบ → แกะ (ไม่มีพ่นเจล/อินฟิวชั่น)', rd['CF'][:4] == ['ทาน้ำยาถอดแบบ','ปูผ้า Carbon Prepreg','เข้าตู้อบ','แกะออกจากแม่พิมพ์'] and 'อินฟิวชั่น' not in rd['CF'], ' → '.join(rd['CF']))
    check('เลขข้อตามเส้นทาง: ประกบ = ข้อ 7 (JelCode) / ข้อ 6 (Carbon) · ไม่มีประกบ = ข้ามและไม่นับเลข',
          E("[stepNo('JN',{route:'JB',has_join:true}), stepNo('JN',{route:'CF',has_join:true}), stepNo('JN',{route:'JB',has_join:false}), stepNo('S7',{route:'JB',has_join:false}), stepNo('S5_1',{route:'B'})]") == ['7','6','','10','5.1'])
    # รับออเดอร์งานเรือ: เลือกสินค้าที่มีประกบ → เส้นทาง JB + ติ๊กประกบให้เอง
    E("startSession(S.data.workers.find(w => w.role==='manager')); S.view='orders'; render()")
    pg.click('[data-act="newOrder"]'); pg.wait_for_selector('#o-no')
    pg.fill('#o-cust', 'อู่เรือทดสอบ')
    ws = E("S.data.products.find(p => p.code==='B-WS-BK').id")
    pg.locator('#o-items .i-prod').first.select_option(ws)
    r1, j1, jv = pg.locator('#o-items .i-route').first.input_value(), pg.locator('#o-items .i-join').first.is_checked(), pg.locator('#o-items .join-f').first.is_visible()
    pg.locator('#o-items .i-qty').first.fill('2')
    pg.click('[data-act="addItemRow"]')
    pg.locator('#o-items .i-prod').last.select_option(E("S.data.products.find(p => p.code==='B-TOP-CF').id"))
    pg.locator('#o-items .i-qty').last.fill('1')
    pg.locator('#o-items .i-join').last.check()
    pg.click('[data-act="saveOrder"]'); pg.wait_for_timeout(300)
    bp = E("S.data.pieces.slice(-3).map(p => [p.route, p.has_join, M.state[p.id].status, M.state[p.id].step])")
    check('เลือกสินค้าเรือ → เส้นทาง JB และติ๊ก "มีประกบ" ให้ตามสินค้า', r1 == 'JB' and j1 and jv, f'{r1} {j1} {jv}')
    check('ออเดอร์เรือ → ชิ้นงานเริ่มที่ "ทาน้ำยาถอดแบบ" และจำค่าประกบรายชิ้น', bp == [['JB', True, 'waiting', 'R0'], ['JB', True, 'waiting', 'R0'], ['CF', True, 'waiting', 'R0']], json.dumps(bp, ensure_ascii=False))
    pg.click('.sheet-head [data-act="closeSheet"]')
    # QC ขั้นสุดท้ายต้องผ่านก่อนห่องาน
    gp = E("S.data.pieces[S.data.pieces.length-3].id")
    E(f"""(() => {{ const p = M.piece['{gp}'], w = S.data.workers[0].id, st = pieceSteps(p), fin = routeDef(p.route).qcFinal; let t = Date.now() - 8*3600e3;
        for(const k of st.slice(0, st.indexOf(fin) + 1)){{ S.data.step_logs.push({{id:uid(), piece_id:p.id, step:k, worker_id:w, finished_by:w, started_at:new Date(t).toISOString(), finished_at:new Date(t+600e3).toISOString(), passes:null, materials:[], note:null, photo_url:null, status:'done', created_at:new Date(t).toISOString()}}); t += 700e3 }}
        demoSave(); reindex(); render() }})()""")
    g1 = E(f"[M.state['{gp}'].status, M.state['{gp}'].step]")
    check('ล้างเสร็จแต่ยังไม่ผ่าน QC → ยังห่องานไม่ได้ (รอ QC)', g1 == ['qc', 'S7'] and E(f"qcPending().some(x => x.piece.id==='{gp}' && x.kind==='final')"), str(g1))
    E(f"openSheet(shPiece,'{gp}')")
    check('ใบงานบอกว่าต้องผ่าน QC ก่อนห่องาน', 'ผ่าน QC แล้วจึงห่องานได้' in pg.locator('#sheetBody').inner_text())
    pg.click('#sheetBody [data-act="openQC"]'); pg.wait_for_selector('#qc-point')
    check('เปิด QC จากใบงาน → เลือกจุด "ขั้นสุดท้ายก่อนส่ง" ให้เอง', pg.locator('#qc-point').input_value() == 'S7' and 'ขั้นสุดท้ายก่อนส่ง' in pg.locator('#qc-point option:checked').inner_text())
    pg.click('[data-act="saveQC"]')
    if pg.locator('#modal:not([hidden])').count(): pin('ประเสริฐ')
    pg.wait_for_timeout(300)
    g2 = E(f"[M.state['{gp}'].status, M.state['{gp}'].step, stepLabel(M.state['{gp}'].step, M.piece['{gp}'])]")
    check('ผ่าน QC → ขั้นถัดไปคือ "12 ห่องานพร้อมส่ง"', g2 == ['waiting', 'WR', '12 ห่องานพร้อมส่ง'], str(g2))
    E(f"S.session=null; openSheet(shPiece,'{gp}')"); pg.click('[data-act="startStep"]'); pin('สุดา')
    pg.click('[data-act="finishStep"]'); pin('สุดา')
    check('ห่องานเสร็จ → พร้อมส่ง', E(f"M.state['{gp}'].status") == 'done')
    # หน้างาน: ปุ่มจุดงานเรือ + ป้าย "เฉพาะงานเรือ"
    E("closeSheet(); S.view='floor'; render()")
    check('หน้างานมีจุดงานเรือ (ทาน้ำยาถอดแบบ, แกะแม่พิมพ์, ห่องาน) พร้อมป้ายเฉพาะงานเรือ',
          all(pg.locator(f'.stepbtn[data-v="{k}"]').count() == 1 for k in ['R0','DM','WR']) and 'เฉพาะงานเรือ' in pg.locator('.stepbtn[data-v="R0"]').inner_text())
    # สูตรมาตรฐานสินค้าเรือ: แสดงเฉพาะขั้นของเส้นทาง · เปลี่ยนเส้นทางแล้วช่องเปลี่ยนตาม
    E("S.session={worker:S.data.workers.find(w=>w.role==='manager'),until:Date.now()+9e6}; S.view='settings'; S.setTab='products'; render()")
    E("openSheet(shProductForm, S.data.products.find(p => p.code==='B-TOP-CF').id)")
    vis = lambda: E("[...document.querySelectorAll('.std-step')].filter(e => !e.hidden).map(e => e.dataset.stdStep)")
    v1 = vis(); pg.select_option('#p-route', 'CP'); v2 = vis(); pg.check('#p-join'); v3 = vis()
    check('สูตรมาตรฐาน: เห็นเฉพาะขั้นของเส้นทาง Carbon → เปลี่ยนเป็นสีตามลูกค้า → ติ๊กประกบ', 'CF1' in v1 and 'S1' not in v1 and 'PC' in v2 and 'CF1' not in v2 and 'JN' not in v2 and 'JN' in v3, f'{len(v1)}/{len(v2)}/{len(v3)}')
    E("closeSheet(); S.session=null; S.view='floor'; render()")

    # ---------- แผนงาน (Kanban) ----------
    E("S.session=null; S.view='floor'; closeSheet(); render()")
    pg.click('.tab[data-v="kanban"]'); pg.wait_for_selector('.kb')
    check('แท็บแผนงานเปิดดูได้โดยไม่ต้องใส่ PIN', E("S.view") == 'kanban' and not pg.locator('#modal').is_visible())
    exp = E("S.data.pieces.filter(p => !p.scrapped && kbStage(p)).length")
    colsum = E("[...document.querySelectorAll('.kb-col .kb-head .n')].reduce((a,e) => a + (parseInt(e.textContent) || 0), 0)")
    check('ทุกชิ้นที่ยังไม่จบอยู่ในคอลัมน์เดียวของบอร์ด (ผลรวมคอลัมน์ = จำนวนชิ้น)', colsum == exp and exp > 0, f'{colsum} / {exp}')
    check('ตารางสรุปตามสินค้า: ยอดรวมตรงกับบอร์ด', pg.locator('.kb-matrix tfoot td').nth(2).inner_text().strip() == str(exp))
    hidden_n = E("document.querySelectorAll('.kb-col').length")
    pg.click('.seg[data-name="kball"] button[data-v="1"]')
    check('ปุ่ม "ทุกขั้น" แสดงขั้นที่ว่างครบตามลำดับการผลิต', E("document.querySelectorAll('.kb-col').length") > hidden_n and E("document.querySelector('.kb-col').dataset.col") in ('R0','S1'))
    pg.click('.seg[data-name="kball"] button[data-v="0"]')
    pg.click('.seg[data-name="kbf"] button[data-v="boat"]')
    rts = E("[...document.querySelectorAll('.kb-card')].map(c => c.dataset.route)")
    check('กรอง "งานเรือ" → เห็นแต่การ์ดเส้นทางเรือ', rts and all(r in ('JB','JW','CP','CF') for r in rts), ','.join(sorted(set(rts))))
    card = pg.locator('.kb-card').first; qn = int(card.locator('.q').inner_text())
    card.click(); pg.wait_for_selector('#sheetBody .pcard')
    check('แตะการ์ด → เห็นรายชิ้นของกลุ่มนั้นครบ แตะต่อเพื่อเปิดใบงานได้', pg.locator('#sheetBody .pcard').count() == qn)
    pg.locator('#sheetBody .pcard').first.click(); pg.wait_for_timeout(200)
    check('เปิดใบงานจากแผนงานได้', E("S.sheet.fn === shPiece"))
    E("S.kbFilter='all'; closeSheet(); S.view='floor'; render()")

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
        E("closeSheet(); openSheet(shOrderForm); const s = document.querySelector('.i-prod'); s.value = S.data.products.find(p => p.code==='B-WS-BK').id; s.dispatchEvent(new Event('change', {bubbles:true}))"); pg.wait_for_timeout(100)
        o5 = E("document.querySelector('.sheet-panel').scrollWidth - document.querySelector('.sheet-panel').clientWidth")
        if tag == 'phone': pg.screenshot(path=f'{SHOTS}/11_phone_boat_order.png')
        E("closeSheet(); S.session=null; S.view='kanban'; render()"); pg.wait_for_timeout(100)
        o6 = overflow()
        if tag == 'phone': pg.screenshot(path=f'{SHOTS}/12_phone_kanban.png')
        E("S.view='floor'; render()")
        if tag == 'phone': pg.screenshot(path=f'{SHOTS}/09_phone_floor.png')
        check(f'ไม่ล้นจอแนวนอน ({tag} {vw}px)', max(o1,o2,o3,o4,o5,o6) <= 0, f'หน้างาน {o1} ใบงาน {o2} dashboard {o3} สูตร {o4} ออเดอร์เรือ {o5} แผนงาน {o6}')
    pg.set_viewport_size({'width':1024,'height':768})
    pg.emulate_media(color_scheme='dark'); E("S.view='floor'; render()"); pg.wait_for_timeout(150)
    pg.screenshot(path=f'{SHOTS}/10_dark_floor.png')
    check('ไม่มี error ใน console', not errors, ' | '.join(errors[:5]))
    b.close()
srv.shutdown()
for r in results: print(*r, sep='\t')
print('TOTAL', sum(r[0]=='PASS' for r in results), '/', len(results))
sys.exit(0 if all(r[0]=='PASS' for r in results) else 1)
