alter table public.work_snapshots
  add column if not exists auth_views bigint,
  add column if not exists auth_source text,
  add column if not exists auth_rank integer,
  add column if not exists auth_observed_at timestamptz;

comment on column public.work_snapshots.auth_views is '작품별 24시간 목표시각 근처에서 확인한 인증조회수';
comment on column public.work_snapshots.auth_source is 'today 또는 new';
comment on column public.work_snapshots.auth_rank is '인증조회수 관측 당시 순위';
comment on column public.work_snapshots.auth_observed_at is '인증조회수 관측 시각';

notify pgrst, 'reload schema';
