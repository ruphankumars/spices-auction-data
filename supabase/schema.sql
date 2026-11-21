-- Spices Board e-auction data. Paste into Supabase › SQL Editor › Run (once).
create table if not exists reports (
  href text primary key, n int, report_date text, auctioneer text, url text,
  sha256 text, batch text, loaded_at timestamptz default now());
create table if not exists auctions (
  auction_id text primary key, auctioneer text, branch text, auction_date date, auction_no text,
  arrivals_kg numeric, sold_kg numeric, withdrawn_kg numeric, value_rs numeric,
  max_rs numeric, min_rs numeric, avg_rs numeric, lots_found int, lots_kg numeric, coverage_pct numeric, batch text);
create table if not exists lots (
  auction_id text references auctions(auction_id) on delete cascade, lot_no text, seller text, buyer text,
  qty_kg numeric, rate_rs numeric, value_rs numeric, ocr_repaired int, seq int,
  primary key (auction_id, seq));
create index if not exists lots_buyer on lots(buyer);
create index if not exists lots_seller on lots(seller);
create index if not exists auctions_date on auctions(auction_date);
-- Public data, read-only to the world; writes only with the service key.
alter table reports enable row level security;
alter table auctions enable row level security;
alter table lots enable row level security;
create policy "read reports" on reports for select using (true);
create policy "read auctions" on auctions for select using (true);
create policy "read lots" on lots for select using (true);
-- The Data API sees only what is granted.
grant usage on schema public to anon, authenticated, service_role;
grant select on reports, auctions, lots to anon, authenticated;
grant all on reports, auctions, lots to service_role;
