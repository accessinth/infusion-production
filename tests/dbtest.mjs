import { PGlite } from '@electric-sql/pglite';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { readFileSync } from 'fs';
import { createHash, randomUUID } from 'crypto';

const db = new PGlite({ extensions: { pgcrypto } });
const R = [];
const ok = (name, cond, info = '') => R.push([cond ? 'PASS' : 'FAIL', name, info]);
const q = async (sql, params) => (await db.query(sql, params)).rows;
async function expectErr(name, fn, re) {
  try { await fn(); ok(name, false, 'ไม่ error'); } catch (e) { ok(name, !re || re.test(e.message), e.message.slice(0, 90)); }
}

// ---- จำลองสภาพแวดล้อม Supabase ----
await db.exec(`
  create role anon nologin; create role authenticated nologin;
  create schema auth; create table auth.users (id uuid primary key, email text);
  create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
  create schema extensions; create schema storage;
  create table storage.buckets (id text primary key, name text, public boolean);
  create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text, name text);
  alter table storage.objects enable row level security;
  grant usage on schema public, auth, extensions, storage to anon, authenticated;
  grant execute on function auth.uid() to anon, authenticated;
  grant all on all tables in schema storage to anon, authenticated;
`);
// DB_EXPOSE=1 จำลองโปรเจกต์ที่เปิด "Automatically expose new tables" (ให้สิทธิ์ตารางใหม่แก่ anon/authenticated อัตโนมัติ)
// ค่าเริ่มต้นจำลองแบบปิด (เหมือนโปรเจกต์จริง) และตัดสิทธิ์ execute ฟังก์ชันจาก PUBLIC ด้วย = กรณีเข้มที่สุด
const EXPOSE = process.env.DB_EXPOSE === '1';
await db.exec(EXPOSE ? `
  alter default privileges in schema public grant all on tables to anon, authenticated;
  alter default privileges in schema public grant all on functions to anon, authenticated;
` : `
  alter default privileges in schema public revoke execute on functions from public;
`);
console.log('โหมดสิทธิ์:', EXPOSE ? 'expose new tables = เปิด' : 'expose new tables = ปิด (เหมือนโปรเจกต์จริง)');
// ทดสอบ supabase/schema.sql บน Postgres (PGlite) พร้อมจำลอง role/auth/storage แบบ Supabase
// ใช้: cd tests && npm install && node dbtest.mjs
const schema = readFileSync(new URL('../supabase/schema.sql', import.meta.url), 'utf8');
try { await db.exec(schema); ok('รันไฟล์ SQL ครั้งแรก', true); } catch (e) { console.log('SCHEMA ERROR:', e.message, '| where:', e.where, '| pos:', e.position); process.exit(1); }
try { await db.exec(schema); ok('รันไฟล์ SQL ซ้ำได้โดยไม่ error', true); } catch (e) { ok('รันไฟล์ SQL ซ้ำได้โดยไม่ error', false, e.message); }
ok('ข้อมูลเริ่มต้น: วัสดุ 13 รายการ ไม่ซ้ำ', (await q('select count(*)::int n from materials'))[0].n === 13);
ok('ข้อมูลเริ่มต้น: ผู้บริหาร 1 คน ไม่ซ้ำ', (await q("select count(*)::int n from workers where role='manager'"))[0].n === 1);

// ---- ผู้ใช้ 2 บัญชี ----
const stationId = randomUUID(), mgrId = randomUUID();
await q('insert into auth.users values ($1,$2),($3,$4)', [stationId, 'tablet@marshal.local', mgrId, 'boss@marshal.local']);
const profs = await q('select display_name, role from profiles order by display_name');
ok('สร้างผู้ใช้แล้วได้ profile station อัตโนมัติ', profs.length === 2 && profs.every(p => p.role === 'station'), JSON.stringify(profs));
await q("update profiles set role='manager' where display_name='boss@marshal.local'");

const as = async (role, uid) => { await db.exec('reset role'); await db.exec(`select set_config('request.jwt.claim.sub', '${uid || ''}', false)`); await db.exec(`set role ${role}`); };
const mgrWorker = (await q("select id from workers where role='manager'"))[0].id;

// ---- แท็บเล็ต (station) ----
await as('authenticated', stationId);
ok('แท็บเล็ตอ่านวัสดุได้', (await q('select count(*)::int n from materials'))[0].n === 13);
ok('แท็บเล็ตอ่านตาราง workers ตรงไม่ได้ (ซ่อนค่าแรง/PIN)', (await q('select count(*)::int n from workers'))[0].n === 0);
const wp = await q('select * from workers_public');
ok('แท็บเล็ตเห็นรายชื่อผ่าน workers_public โดยไม่มีค่าแรงและ PIN', wp.length === 1 && !('hourly_rate' in wp[0]) && !('pin_hash' in wp[0]), Object.keys(wp[0]).join(','));
ok('ตรวจ PIN ถูก → true', (await q('select verify_pin($1,$2) v', [mgrWorker, '1234']))[0].v === true);
ok('ตรวจ PIN ผิด → false', (await q('select verify_pin($1,$2) v', [mgrWorker, '0000']))[0].v === false);
await expectErr('แท็บเล็ตแก้ราคาวัสดุไม่ได้', async () => { const r = await db.query("update materials set unit_cost = 1 where code='GC-W'"); if (r.affectedRows === 0) throw new Error('0 rows (RLS กันไว้)'); }, /RLS|policy/);
await expectErr('แท็บเล็ตเพิ่มวัสดุไม่ได้', () => q("insert into materials (code,name,category,unit) values ('X','x','other','kg')"), /row-level security/);
await expectErr('แท็บเล็ตตั้ง PIN คนอื่นไม่ได้', () => q('select set_worker_pin($1,$2)', [mgrWorker, '9999']), /เฉพาะบัญชีผู้บริหาร/);

// ---- ผู้บริหาร ----
await as('authenticated', mgrId);
const [w] = await q("insert into workers (name, role, hourly_rate) values ('สมชาย','worker',65) returning id");
await q('select set_worker_pin($1,$2)', [w.id, '5678']);
ok('ผู้บริหารเพิ่มช่างและตั้ง PIN ได้', (await q('select verify_pin($1,$2) v', [w.id, '5678']))[0].v === true);
const expected = createHash('sha256').update(`${w.id}:5678`).digest('hex');
ok('รูปแบบ hash ตรงกับที่แอปใช้ (sha256 ของ id:PIN)', (await q('select pin_hash from workers where id=$1', [w.id]))[0].pin_hash === expected);
await expectErr('PIN ต้องเป็นตัวเลข 4–6 หลัก', () => q('select set_worker_pin($1,$2)', [w.id, '12a']), /PIN/);
ok('ผู้บริหารเห็นค่าแรง', (await q('select hourly_rate from workers where id=$1', [w.id]))[0].hourly_rate == 65);
const gw = (await q("select id from materials where code='GC-W'"))[0].id;
const [prod] = await q(`insert into products (code,name,category,default_route,standard) values ('P-HOOD','ฝากระโปรงหน้า','ชิ้นส่วนรถยนต์','B', $1) returning id`, [JSON.stringify({ S1: { minutes: 35, passes: 2, materials: [{ material_id: gw, qty: 1.4 }] } })]);
await q("update materials set unit_cost = 185 where id=$1", [gw]);
await q("insert into settings (key,value) values ('default_labor_rate','75') on conflict (key) do update set value = excluded.value");
ok('ผู้บริหารเพิ่มสินค้า แก้ราคา แก้ค่าแรงกลางได้', (await q("select value from settings where key='default_labor_rate'"))[0].value === 75);

// ---- งานประจำวันบนแท็บเล็ต ----
await as('authenticated', stationId);
const oid = randomUUID(), iid = randomUUID(), pid = randomUUID(), lid = randomUUID();
await q("insert into orders (id, order_no, customer, due_date, created_by) values ($1,'IF2611-001','ทดสอบ', current_date + 7, $2)", [oid, mgrWorker]);
await q("insert into order_items (id, order_id, product_id, qty, route) values ($1,$2,$3,1,'B')", [iid, oid, prod.id]);
await q("insert into pieces (id, code, order_id, order_item_id, product_id, route, seq) values ($1,'IF2611-001-01',$2,$3,$4,'B',1)", [pid, oid, iid, prod.id]);
await q("insert into step_logs (id, piece_id, step, worker_id) values ($1,$2,'S1',$3)", [lid, pid, w.id]);
await q("update step_logs set status='done', finished_at=now(), finished_by=$2, passes=2, materials=$3 where id=$1", [lid, w.id, JSON.stringify([{ material_id: gw, qty: 1.52 }])]);
await q("insert into qc_records (piece_id, step, inspector_id, result, defect, rework_step) values ($1,'S7',$2,'rework','รอยขัด/ขนแมว','S6')", [pid, mgrWorker]);
await q("insert into stock_receipts (material_id, qty, unit_cost, kind, worker_id) values ($1, 20, 185, 'receive', $2)", [gw, mgrWorker]);
await q("update pieces set scrapped=true, scrap_reason='ฟองอากาศ' where id=$1", [pid]);
const lg = (await q('select status, materials from step_logs where id=$1', [lid]))[0];
ok('แท็บเล็ตบันทึก ออเดอร์ → ชิ้นงาน → เริ่ม/เสร็จงาน → QC → รับวัสดุ ได้ครบ', lg.status === 'done' && lg.materials[0].qty === 1.52);
await expectErr('กันสถานะที่ไม่ถูกต้อง', () => q("update step_logs set status='finished' where id=$1", [lid]), /check/);
await expectErr('กันเลขออเดอร์ซ้ำ', () => q("insert into orders (order_no) values ('IF2611-001')"), /duplicate|unique/);
await q("insert into step_logs (piece_id, step, worker_id) values ($1,'S2',$2)", [pid, w.id]);
await expectErr('กันแท็บเล็ต 2 เครื่องกดเริ่มชิ้นเดียวกันพร้อมกัน', () => q("insert into step_logs (piece_id, step, worker_id) values ($1,'S2',$2)", [pid, w.id]), /one_active_step_per_piece/);
const del = await db.query('delete from orders where id=$1', [oid]);
ok('แท็บเล็ตลบออเดอร์ไม่ได้', del.affectedRows === 0 && (await q('select count(*)::int n from orders'))[0].n === 1);
await q("insert into storage.objects (bucket_id, name) values ('qc-photos','2026-11/x.jpg')");
ok('แท็บเล็ตอัปโหลดรูป QC ได้', (await q("select count(*)::int n from storage.objects where bucket_id='qc-photos'"))[0].n === 1);
await expectErr('อัปโหลดเข้า bucket อื่นไม่ได้', () => q("insert into storage.objects (bucket_id, name) values ('other','x')"), /row-level security/);

// ---- คนนอก (anon) ----
await as('anon');
// คนนอก: ได้ 0 แถว (RLS กัน) หรือถูกปฏิเสธทั้งตาราง (ไม่มีสิทธิ์ตาราง) ก็ถือว่าผ่าน
const anonSees = async t => { try { return (await q(`select count(*)::int n from ${t}`))[0].n; } catch (e) { return /permission denied/.test(e.message) ? 'denied' : e.message; } };
const anonRes = await Promise.all(['orders', 'materials', 'workers', 'step_logs'].map(anonSees));
ok('คนนอกที่ไม่ล็อกอินอ่านข้อมูลไม่ได้', anonRes.every(v => v === 0 || v === 'denied'), anonRes.join(','));
await expectErr('คนนอกเขียนข้อมูลไม่ได้', () => q("insert into orders (order_no) values ('HACK-1')"), /permission denied|row-level security/);
await expectErr('คนนอกอ่านรายชื่อช่างไม่ได้', () => q('select * from workers_public'), /permission denied/);
await expectErr('คนนอกเดา PIN ไม่ได้', () => q('select verify_pin($1,$2)', [mgrWorker, '1234']), /permission denied/);

await db.exec('reset role');
for (const r of R) console.log(r.join('\t'));
console.log('TOTAL', R.filter(r => r[0] === 'PASS').length, '/', R.length);
process.exit(R.every(r => r[0] === 'PASS') ? 0 : 1);
