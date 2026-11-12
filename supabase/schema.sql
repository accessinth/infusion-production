-- =====================================================================
--  MARSHAL · ระบบบันทึกการผลิตแผนกอินฟิวชั่น
--  Supabase schema  (วางทั้งไฟล์ใน Supabase → SQL Editor → Run · รันซ้ำได้ ไม่ทำข้อมูลเดิมเสีย)
-- =====================================================================
--  แนวคิดสิทธิ์ 2 ชั้น
--   ชั้นที่ 1  บัญชีเครื่อง (Supabase Auth)
--      station   = แท็บเล็ตประจำจุด  : บันทึกงาน/QC/ออเดอร์/รับวัสดุได้  แก้ข้อมูลหลักไม่ได้  ไม่เห็นค่าแรง
--      manager   = บัญชีผู้บริหาร    : ทำได้ทุกอย่าง รวมถึงแก้ข้อมูลหลัก (ช่าง วัสดุ สินค้า สูตรมาตรฐาน) และเห็นค่าแรง
--   ชั้นที่ 2  ตัวบุคคล (PIN 4–6 หลัก ในตาราง workers)
--      worker / supervisor / manager  → แอปใช้ PIN ระบุว่า "ใครทำ" ทุกครั้งที่บันทึก
--      และใช้ปลดล็อกหน้าที่ตามบทบาท (QC/ออเดอร์/สต็อก = supervisor ขึ้นไป, ผู้บริหาร = manager)
--  หมายเหตุ: PIN ใช้ระบุตัวคนบนเครื่องที่ใช้ร่วมกัน ไม่ใช่รหัสผ่านความปลอดภัยสูง
-- =====================================================================

create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------
-- บัญชีเครื่อง / ผู้ใช้ระบบ
-- ---------------------------------------------------------------------
create table if not exists public.profiles (
  id           uuid primary key references auth.users on delete cascade,
  display_name text,
  role         text not null default 'station' check (role in ('station','manager')),
  created_at   timestamptz not null default now()
);

create or replace function public.app_role() returns text
language sql stable security definer set search_path = public as $$
  select coalesce((select role from public.profiles where id = auth.uid()), 'none')
$$;

create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, display_name) values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- ข้อมูลหลัก
-- ---------------------------------------------------------------------
create table if not exists public.workers (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  role        text not null default 'worker' check (role in ('worker','supervisor','manager')),
  hourly_rate numeric(10,2) not null default 0,          -- ค่าแรงต่อชั่วโมง (บาท) ใช้คิดต้นทุนจริง
  pin_hash    text,
  color       text,
  active      boolean not null default true,
  created_at  timestamptz not null default now()
);

-- ภาษาบนจอของช่างแต่ละคน: th ไทย | km เขมร | my พม่า (จอเปลี่ยนให้หลังใส่ PIN)
alter table public.workers add column if not exists lang text not null default 'th';
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'workers_lang_check') then
    alter table public.workers add constraint workers_lang_check check (lang in ('th','km','my'));
  end if;
end $$;

-- มุมมองสำหรับแท็บเล็ต: ไม่มี pin_hash และค่าแรง (คอลัมน์ใหม่ต้องต่อท้ายเสมอ)
create or replace view public.workers_public as
  select id, name, role, color, active, created_at, lang from public.workers;

create table if not exists public.materials (
  id            uuid primary key default gen_random_uuid(),
  code          text unique not null,
  name          text not null,
  category      text not null check (category in ('gelcoat','fiber','resin','polish','release','carbon','putty','paint','other')),
  unit          text not null check (unit in ('kg','m','pcs')),   -- kg ป้อนเป็นกรัมได้ในแอป
  unit_cost     numeric(12,2) not null default 0,                 -- บาท/หน่วย
  reorder_level numeric(12,3) not null default 0,
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

-- standard (jsonb) = สูตรมาตรฐานต่อขั้นตอน เช่น
-- {"S1":{"minutes":40,"passes":2,"materials":[{"material_id":"…","qty":1.2}]},
--  "S2":{"minutes":90,"materials":[{"material_id":"<ใยผิว>","qty":2},{"material_id":"<#400>","qty":4}]}, …}
create table if not exists public.products (
  id            uuid primary key default gen_random_uuid(),
  code          text unique not null,
  name          text not null,
  category      text,
  default_route text not null default 'A' check (default_route in ('A','B','JB','JW','CP','CF')),  -- ดูคำอธิบายเส้นทางในส่วน "งานเรือ"
  standard      jsonb not null default '{}',
  active        boolean not null default true,
  created_at    timestamptz not null default now()
);

create table if not exists public.settings (
  key   text primary key,
  value jsonb
);

-- ---------------------------------------------------------------------
-- ออเดอร์และชิ้นงาน
-- ---------------------------------------------------------------------
create table if not exists public.orders (
  id            uuid primary key default gen_random_uuid(),
  order_no      text unique not null,
  customer      text,
  received_date date not null default current_date,
  due_date      date,
  note          text,
  created_by    uuid references public.workers,
  created_at    timestamptz not null default now()
);

create table if not exists public.order_items (
  id         uuid primary key default gen_random_uuid(),
  order_id   uuid not null references public.orders on delete cascade,
  product_id uuid not null references public.products,
  qty        int  not null check (qty > 0),
  route      text not null check (route in ('A','B','JB','JW','CP','CF')),
  created_at timestamptz not null default now()
);

create table if not exists public.pieces (
  id            uuid primary key default gen_random_uuid(),
  code          text unique not null,                    -- รหัสบน QR เช่น IF2611-001-03
  order_id      uuid not null references public.orders on delete cascade,
  order_item_id uuid not null references public.order_items on delete cascade,
  product_id    uuid not null references public.products,
  route         text not null check (route in ('A','B','JB','JW','CP','CF')),
  seq           int  not null,
  scrapped      boolean not null default false,
  scrap_reason  text,
  replaces      uuid references public.pieces,          -- ชิ้นทดแทนของชิ้นที่เสีย
  created_at    timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- งานเรือ (12 พ.ย. 2026) · ฐานข้อมูลที่สร้างจาก schema เดิมได้รับการแก้ตรงนี้เมื่อรันไฟล์ซ้ำ
--   เส้นทาง: A เก็บผิว | B พ่นเรซินเจลโค้ตเพิ่ม | JB เรือ JelCode ดำ | JW เรือ JelCode ขาว |
--           CP เรือ สีตามลูกค้าสั่ง | CF เรือ Carbon
--   has_join = ชิ้นงานมีขั้นประกบ (ค่าเริ่มต้นจากสินค้า → รายการในออเดอร์ → ชิ้นงาน)
-- ---------------------------------------------------------------------
alter table public.products    add column if not exists has_join boolean not null default false;
alter table public.order_items add column if not exists has_join boolean not null default false;
alter table public.pieces      add column if not exists has_join boolean not null default false;

alter table public.products    drop constraint if exists products_default_route_check;
alter table public.products    add  constraint products_default_route_check check (default_route in ('A','B','JB','JW','CP','CF'));
alter table public.order_items drop constraint if exists order_items_route_check;
alter table public.order_items add  constraint order_items_route_check check (route in ('A','B','JB','JW','CP','CF'));
alter table public.pieces      drop constraint if exists pieces_route_check;
alter table public.pieces      add  constraint pieces_route_check check (route in ('A','B','JB','JW','CP','CF'));
alter table public.materials   drop constraint if exists materials_category_check;
alter table public.materials   add  constraint materials_category_check check (category in ('gelcoat','fiber','resin','polish','release','carbon','putty','paint','other'));

-- ---------------------------------------------------------------------
-- บันทึกการทำงานแต่ละขั้นตอน
-- step: S1 เจลโค้ต | S2 ปูใยแก้ว | S3 อินฟิวชั่น | S4 เจียรตัดแต่ง |
--       S5 เก็บผิว (เส้นทาง A) | S5_1 พ่นเรซินเจลโค้ต, S5_2 ขัดเก็บผิว (เส้นทาง B และงานเรือ) |
--       S6 ขัดเงา | S7 ล้าง เตรียมส่ง
--       งานเรือ: R0 ทาน้ำยาถอดแบบ | CF1 ปูผ้า Carbon Prepreg | CF2 เข้าตู้อบ | DM แกะออกจากแม่พิมพ์ |
--       JN ประกบชิ้นงาน | PT โป๊ว | PR สีพื้น | PC สีตามลูกค้า | LQ แล็คเกอร์ | WR ห่องานพร้อมส่ง
-- materials: [{"material_id":"…","qty":1.25,"layer":1}]  (qty เป็นหน่วยหลักของวัสดุ)
-- status: in_progress | done | cancelled (กดผิด ไม่นับ) | reworked (ถูกสั่งแก้ นับเป็นต้นทุน)
-- ---------------------------------------------------------------------
create table if not exists public.step_logs (
  id          uuid primary key default gen_random_uuid(),
  piece_id    uuid not null references public.pieces on delete cascade,
  step        text not null,
  worker_id   uuid references public.workers,
  finished_by uuid references public.workers,
  started_at  timestamptz not null default now(),
  finished_at timestamptz,
  passes      int,
  materials   jsonb not null default '[]',
  note        text,
  photo_url   text,
  status      text not null default 'in_progress'
              check (status in ('in_progress','done','cancelled','reworked')),
  created_at  timestamptz not null default now()
);

create table if not exists public.qc_records (
  id           uuid primary key default gen_random_uuid(),
  piece_id     uuid not null references public.pieces on delete cascade,
  step         text not null,                 -- จุดตรวจ เช่น S3 หรือ S7
  inspector_id uuid references public.workers,
  result       text not null check (result in ('pass','rework','scrap')),
  defect       text,
  rework_step  text,
  note         text,
  photo_url    text,
  created_at   timestamptz not null default now()
);

-- รับเข้า (+) หรือปรับยอด (+/-) ; ยอดใช้จริงคำนวณจาก step_logs.materials
create table if not exists public.stock_receipts (
  id          uuid primary key default gen_random_uuid(),
  material_id uuid not null references public.materials,
  qty         numeric(12,3) not null,
  unit_cost   numeric(12,2),
  kind        text not null default 'receive' check (kind in ('receive','adjust')),
  note        text,
  worker_id   uuid references public.workers,
  created_at  timestamptz not null default now()
);

create index if not exists idx_items_order   on public.order_items (order_id);
create index if not exists idx_pieces_order  on public.pieces (order_id);
create index if not exists idx_logs_piece    on public.step_logs (piece_id);
create index if not exists idx_logs_worker   on public.step_logs (worker_id, started_at);
create index if not exists idx_qc_piece      on public.qc_records (piece_id);
create index if not exists idx_receipts_mat  on public.stock_receipts (material_id);

-- กันแท็บเล็ต 2 เครื่องกด "เริ่มงาน" ชิ้นเดียวกันพร้อมกัน: 1 ชิ้นมีงานที่กำลังทำได้ครั้งละ 1 รายการ
create unique index if not exists one_active_step_per_piece
  on public.step_logs (piece_id) where status = 'in_progress';

-- ---------------------------------------------------------------------
-- PIN
-- ---------------------------------------------------------------------
create or replace function public.verify_pin(p_worker uuid, p_pin text) returns boolean
language sql stable security definer set search_path = public, extensions as $$
  select exists (
    select 1 from public.workers
    where id = p_worker and active
      and pin_hash = encode(digest(p_worker::text || ':' || p_pin, 'sha256'), 'hex'))
$$;

create or replace function public.set_worker_pin(p_worker uuid, p_pin text) returns void
language plpgsql security definer set search_path = public, extensions as $$
begin
  if public.app_role() <> 'manager' then raise exception 'เฉพาะบัญชีผู้บริหาร'; end if;
  if p_pin !~ '^[0-9]{4,6}$' then raise exception 'PIN ต้องเป็นตัวเลข 4–6 หลัก'; end if;
  update public.workers
     set pin_hash = encode(digest(p_worker::text || ':' || p_pin, 'sha256'), 'hex')
   where id = p_worker;
end $$;

revoke all on function public.verify_pin(uuid,text)     from public, anon;
revoke all on function public.set_worker_pin(uuid,text) from public, anon;
grant execute on function public.verify_pin(uuid,text)     to authenticated;
grant execute on function public.set_worker_pin(uuid,text) to authenticated;

-- ---------------------------------------------------------------------
-- สิทธิ์ระดับตาราง (Data API)
-- โปรเจกต์ปิด "Automatically expose new tables" ไว้ จึงให้สิทธิ์เองตรงนี้
-- ให้เฉพาะผู้ที่ล็อกอินแล้ว (authenticated) · คนนอก (anon) ไม่ได้สิทธิ์ตารางใดเลย
-- แถวไหนอ่าน/แก้ได้ ยังถูกคุมด้วย RLS ด้านล่างอีกชั้น
-- ---------------------------------------------------------------------
grant usage on schema public to authenticated;
grant select, insert, update, delete on
  public.profiles, public.workers, public.materials, public.products, public.settings,
  public.orders, public.order_items, public.pieces, public.step_logs, public.qc_records, public.stock_receipts
  to authenticated;
revoke all on
  public.profiles, public.workers, public.materials, public.products, public.settings,
  public.orders, public.order_items, public.pieces, public.step_logs, public.qc_records, public.stock_receipts
  from anon;
revoke all on function public.app_role() from public, anon;
grant execute on function public.app_role() to authenticated;

-- ---------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------
alter table public.profiles       enable row level security;
alter table public.workers        enable row level security;
alter table public.materials      enable row level security;
alter table public.products       enable row level security;
alter table public.settings       enable row level security;
alter table public.orders         enable row level security;
alter table public.order_items    enable row level security;
alter table public.pieces         enable row level security;
alter table public.step_logs      enable row level security;
alter table public.qc_records     enable row level security;
alter table public.stock_receipts enable row level security;

-- profiles
drop policy if exists "profile: อ่าน" on public.profiles;
create policy "profile: อ่าน" on public.profiles
  for select to authenticated using (id = auth.uid() or public.app_role() = 'manager');
drop policy if exists "profile: ผู้บริหารแก้ไข" on public.profiles;
create policy "profile: ผู้บริหารแก้ไข" on public.profiles
  for update to authenticated using (public.app_role() = 'manager');

-- workers: ตารางเต็ม (มีค่าแรง) เฉพาะผู้บริหาร ; เครื่องทั่วไปอ่านผ่าน workers_public
drop policy if exists "workers: ผู้บริหารเท่านั้น" on public.workers;
create policy "workers: ผู้บริหารเท่านั้น" on public.workers
  for all to authenticated
  using (public.app_role() = 'manager') with check (public.app_role() = 'manager');
revoke all on public.workers_public from anon, public;
grant select on public.workers_public to authenticated;

-- ข้อมูลหลัก: ทุกเครื่องอ่านได้ แก้ได้เฉพาะผู้บริหาร
do $$
declare t text;
begin
  foreach t in array array['materials','products','settings'] loop
    execute format('drop policy if exists "%1$s: อ่าน" on public.%1$I', t);
    execute format('drop policy if exists "%1$s: ผู้บริหารเพิ่ม" on public.%1$I', t);
    execute format('drop policy if exists "%1$s: ผู้บริหารแก้" on public.%1$I', t);
    execute format('drop policy if exists "%1$s: ผู้บริหารลบ" on public.%1$I', t);
    execute format('create policy "%1$s: อ่าน" on public.%1$I for select to authenticated using (public.app_role() in (''station'',''manager''))', t);
    execute format('create policy "%1$s: ผู้บริหารเพิ่ม" on public.%1$I for insert to authenticated with check (public.app_role() = ''manager'')', t);
    execute format('create policy "%1$s: ผู้บริหารแก้" on public.%1$I for update to authenticated using (public.app_role() = ''manager'')', t);
    execute format('create policy "%1$s: ผู้บริหารลบ" on public.%1$I for delete to authenticated using (public.app_role() = ''manager'')', t);
  end loop;
end $$;

-- ข้อมูลงานประจำวัน: ทุกเครื่องอ่าน/เพิ่ม/แก้ได้ (ทุกแถวบันทึกว่าใครทำ) ลบได้เฉพาะผู้บริหาร
do $$
declare t text;
begin
  foreach t in array array['orders','order_items','pieces','step_logs','qc_records','stock_receipts'] loop
    execute format('drop policy if exists "%1$s: อ่าน" on public.%1$I', t);
    execute format('drop policy if exists "%1$s: เพิ่ม" on public.%1$I', t);
    execute format('drop policy if exists "%1$s: แก้" on public.%1$I', t);
    execute format('drop policy if exists "%1$s: ผู้บริหารลบ" on public.%1$I', t);
    execute format('create policy "%1$s: อ่าน" on public.%1$I for select to authenticated using (public.app_role() in (''station'',''manager''))', t);
    execute format('create policy "%1$s: เพิ่ม" on public.%1$I for insert to authenticated with check (public.app_role() in (''station'',''manager''))', t);
    execute format('create policy "%1$s: แก้" on public.%1$I for update to authenticated using (public.app_role() in (''station'',''manager''))', t);
    execute format('create policy "%1$s: ผู้บริหารลบ" on public.%1$I for delete to authenticated using (public.app_role() = ''manager'')', t);
  end loop;
end $$;

-- ---------------------------------------------------------------------
-- ที่เก็บรูป QC / รูปหน้างาน
-- ---------------------------------------------------------------------
insert into storage.buckets (id, name, public) values ('qc-photos', 'qc-photos', true)
on conflict (id) do nothing;

drop policy if exists "qc-photos: อัปโหลด" on storage.objects;
create policy "qc-photos: อัปโหลด" on storage.objects
  for insert to authenticated with check (bucket_id = 'qc-photos');
-- ไม่มี policy อ่าน/ลิสต์ไฟล์: bucket เป็น public เปิดรูปผ่านลิงก์ได้อยู่แล้ว
-- (Supabase เตือนว่า policy select แบบกว้างทำให้ลิสต์ไฟล์ทั้งหมดได้) · อัปโหลดแบบไม่ทับไฟล์เดิมใช้แค่ insert
drop policy if exists "qc-photos: อ่าน" on storage.objects;

-- ---------------------------------------------------------------------
-- ข้อมูลเริ่มต้น (แก้ราคาวัสดุและชื่อในแอปภายหลัง)
-- ---------------------------------------------------------------------
insert into public.settings (key, value) values
  ('default_labor_rate', '60'::jsonb)          -- บาท/ชม. ใช้เมื่อช่างยังไม่มีค่าแรงรายคน
on conflict (key) do nothing;

insert into public.materials (code, name, category, unit, unit_cost, reorder_level) values
  ('GC-W',     'เจลโค้ต สีขาว',        'gelcoat', 'kg', 0, 20),
  ('GC-BK',    'เจลโค้ต สีดำ',         'gelcoat', 'kg', 0, 20),
  ('FB-SV',    'ใยผิว',                'fiber',   'm',  0, 50),
  ('FB-300',   'ใยแก้ว เบอร์ 300',     'fiber',   'm',  0, 50),
  ('FB-400',   'ใยแก้ว เบอร์ 400',     'fiber',   'm',  0, 50),
  ('FB-W600',  'ใยแก้วตาสาน เบอร์ 600', 'fiber',   'm',  0, 30),
  ('FB-W800',  'ใยแก้วตาสาน เบอร์ 800', 'fiber',   'm',  0, 30),
  ('FB-W1000', 'ใยแก้วตาสาน เบอร์ 1000','fiber',   'm',  0, 30),
  ('RS-INF',   'เรซินอินฟิวชั่น',       'resin',   'kg', 0, 60),
  ('RS-GC',    'เรซินเจลโค้ต',          'resin',   'kg', 0, 20),
  ('CAT-MEKP', 'ตัวเร่ง (MEKP)',        'other',   'kg', 0, 2),
  ('PL-C',     'ยาขัด หยาบ',           'polish',  'kg', 0, 2),
  ('PL-F',     'ยาขัด ละเอียด (ลบขนแมว)','polish',  'kg', 0, 2),
  ('RL-WAX',   'น้ำยาถอดแบบ (แว็กซ์)',   'release', 'kg', 0, 1),
  ('CF-PP',    'ผ้าคาร์บอน Prepreg',     'carbon',  'm',  0, 10),
  ('PT-CAR',   'สีโป๊วรถยนต์',           'putty',   'kg', 0, 2),
  ('PA-PRM',   'สีพื้นรถยนต์',           'paint',   'kg', 0, 2),
  ('PA-CLR',   'สีพ่นตามลูกค้าสั่ง',      'paint',   'kg', 0, 1),
  ('PA-LQ',    'แล็คเกอร์',             'paint',   'kg', 0, 2)
on conflict (code) do nothing;

-- ผู้บริหารคนแรก PIN 1234 (เปลี่ยนในแอป → ตั้งค่า → ช่าง)
do $$
declare w uuid;
begin
  if not exists (select 1 from public.workers where role = 'manager') then
    insert into public.workers (name, role) values ('ผู้บริหาร', 'manager') returning id into w;
    update public.workers
       set pin_hash = encode(extensions.digest(w::text || ':1234', 'sha256'), 'hex')
     where id = w;
  end if;
end $$;

-- =====================================================================
--  หลังรัน: สร้างผู้ใช้ใน Authentication → Users (Add user, ติ๊ก Auto Confirm)
--    1) tablet@marshal.local   (แท็บเล็ตหน้างาน)  → role = station อัตโนมัติ
--    2) อีเมลผู้บริหาร          → แล้วรันคำสั่งด้านล่างเพื่อยกเป็น manager
--
--  update public.profiles set role = 'manager' where display_name = 'อีเมลผู้บริหาร';
-- =====================================================================
