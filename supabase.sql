-- Run this once in Supabase: SQL Editor > New query > paste > Run
create table if not exists items (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  url text,
  target numeric,
  bought boolean not null default false,
  selector text,                       -- optional CSS selector for the price (e.g. ".product-price")
  render_js boolean not null default false, -- true = load page in a headless browser
  last_checked timestamptz,
  last_status text,
  created_at timestamptz not null default now()
);

create table if not exists prices (
  id uuid primary key default gen_random_uuid(),
  item_id uuid not null references items(id) on delete cascade,
  price numeric not null,
  store text,
  sale boolean not null default false,
  source text not null default 'manual', -- 'manual' or 'auto'
  on_date date not null default current_date,
  created_at timestamptz not null default now()
);
create index if not exists prices_item_idx on prices(item_id, on_date);

-- Only logged-in household members can read/write. Disable public sign-ups in
-- Authentication settings so nobody else can create an account.
alter table items  enable row level security;
alter table prices enable row level security;
create policy "household items"  on items  for all to authenticated using (true) with check (true);
create policy "household prices" on prices for all to authenticated using (true) with check (true);
