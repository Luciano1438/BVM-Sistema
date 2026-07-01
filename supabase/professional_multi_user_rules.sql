-- BVM professional multi-user contract.
-- Execute this after the base tables exist.
--
-- Core rules:
-- 1. Personal data: taller_id is null and user_id = auth.uid().
-- 2. Shared workshop data: taller_id is not null and the user is the owner
--    or an active member of that workshop.
-- 3. A member who leaves the workshop loses access to shared rows, including
--    rows they originally created inside the workshop.
-- 4. Workshop configuration is owned by the workshop owner. Employees can read
--    the operative configuration used by the app, but cannot write it.

alter table public.ventas
  add column if not exists taller_id uuid references public.talleres(id),
  add column if not exists user_id uuid references auth.users(id);

alter table public.configuracion
  add column if not exists taller_id uuid references public.talleres(id),
  add column if not exists user_id uuid references auth.users(id);

alter table public.retazos
  add column if not exists taller_id uuid references public.talleres(id),
  add column if not exists user_id uuid references auth.users(id);

create index if not exists idx_ventas_taller_id on public.ventas(taller_id);
create index if not exists idx_ventas_user_id on public.ventas(user_id);
create index if not exists idx_configuracion_taller_id on public.configuracion(taller_id);
create index if not exists idx_configuracion_user_id on public.configuracion(user_id);
create index if not exists idx_retazos_taller_id on public.retazos(taller_id);
create index if not exists idx_retazos_user_id on public.retazos(user_id);
create index if not exists idx_miembros_taller_taller_user on public.miembros_taller(taller_id, user_id);
create index if not exists idx_talleres_owner_id on public.talleres(owner_id);

-- Make every owner an explicit member too. The app also does this, but this
-- keeps old workshops consistent.
insert into public.miembros_taller (taller_id, user_id, rol)
select t.id, t.owner_id, U&'due\00F1o'
from public.talleres t
where not exists (
  select 1
  from public.miembros_taller mt
  where mt.taller_id = t.id
    and mt.user_id = t.owner_id
);

-- Share only old owner rows with their workshop. This never migrates
-- collaborator personal rows into a boss workshop.
update public.ventas v
set taller_id = t.id
from public.talleres t
where v.taller_id is null
  and v.user_id = t.owner_id;

update public.configuracion c
set taller_id = t.id
from public.talleres t
where c.taller_id is null
  and c.user_id = t.owner_id;

update public.retazos r
set taller_id = t.id
from public.talleres t
where r.taller_id is null
  and r.user_id = t.owner_id;

-- If a collaborator accidentally wrote workshop configuration under their own
-- user_id, move it back to their personal scope so it cannot override owner
-- prices in shared workshop reads.
update public.configuracion c
set taller_id = null
from public.talleres t
where c.taller_id = t.id
  and c.user_id is distinct from t.owner_id;

create or replace function public.bvm_is_workshop_owner(p_taller_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.talleres t
    where t.id = p_taller_id
      and t.owner_id = auth.uid()
  );
$$;

create or replace function public.bvm_is_workshop_member(p_taller_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.miembros_taller mt
    where mt.taller_id = p_taller_id
      and mt.user_id = auth.uid()
  );
$$;

grant execute on function public.bvm_is_workshop_owner(uuid) to authenticated;
grant execute on function public.bvm_is_workshop_member(uuid) to authenticated;

create or replace function public.guardar_configuracion_bvm_v2(
  p_clave text,
  p_valor double precision,
  p_categoria text,
  p_owner_id uuid,
  p_taller_id uuid
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_owner_id uuid;
begin
  if v_uid is null then
    raise exception 'Usuario no autenticado';
  end if;

  if p_taller_id is not null then
    select t.owner_id
      into v_owner_id
    from public.talleres t
    where t.id = p_taller_id;

    if v_owner_id is null then
      raise exception 'Taller inexistente';
    end if;

    if v_owner_id is distinct from v_uid then
      raise exception 'Solo el dueno del taller puede modificar precios';
    end if;

    if p_owner_id is distinct from v_owner_id then
      raise exception 'Owner invalido para el taller';
    end if;
  else
    v_owner_id := v_uid;
  end if;

  update public.configuracion c
  set valor = p_valor,
      categoria = p_categoria,
      taller_id = p_taller_id
  where c.user_id = v_owner_id
    and c.clave = p_clave;

  if not found then
    insert into public.configuracion (user_id, taller_id, clave, valor, categoria)
    values (v_owner_id, p_taller_id, p_clave, p_valor, p_categoria);
  end if;
end;
$$;

grant execute on function public.guardar_configuracion_bvm_v2(text, double precision, text, uuid, uuid) to authenticated;

alter table public.ventas enable row level security;
alter table public.configuracion enable row level security;
alter table public.retazos enable row level security;

drop policy if exists ventas_select_scope on public.ventas;
create policy ventas_select_scope
on public.ventas for select
to authenticated
using (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and (
      public.bvm_is_workshop_owner(taller_id)
      or public.bvm_is_workshop_member(taller_id)
    )
  )
);

drop policy if exists ventas_insert_scope on public.ventas;
create policy ventas_insert_scope
on public.ventas for insert
to authenticated
with check (
  user_id = auth.uid()
  and (
    taller_id is null
    or public.bvm_is_workshop_owner(taller_id)
    or public.bvm_is_workshop_member(taller_id)
  )
);

drop policy if exists ventas_update_scope on public.ventas;
create policy ventas_update_scope
on public.ventas for update
to authenticated
using (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and (
      public.bvm_is_workshop_owner(taller_id)
      or public.bvm_is_workshop_member(taller_id)
    )
  )
)
with check (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and (
      public.bvm_is_workshop_owner(taller_id)
      or public.bvm_is_workshop_member(taller_id)
    )
  )
);

drop policy if exists ventas_delete_scope on public.ventas;
create policy ventas_delete_scope
on public.ventas for delete
to authenticated
using (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and (
      public.bvm_is_workshop_owner(taller_id)
      or public.bvm_is_workshop_member(taller_id)
    )
  )
);

drop policy if exists configuracion_select_scope on public.configuracion;
create policy configuracion_select_scope
on public.configuracion for select
to authenticated
using (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and (
      public.bvm_is_workshop_owner(taller_id)
      or public.bvm_is_workshop_member(taller_id)
    )
  )
);

drop policy if exists configuracion_write_scope on public.configuracion;
create policy configuracion_write_scope
on public.configuracion for all
to authenticated
using (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and public.bvm_is_workshop_owner(taller_id)
    and user_id = auth.uid()
  )
)
with check (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and public.bvm_is_workshop_owner(taller_id)
    and user_id = auth.uid()
  )
);

drop policy if exists retazos_select_scope on public.retazos;
create policy retazos_select_scope
on public.retazos for select
to authenticated
using (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and (
      public.bvm_is_workshop_owner(taller_id)
      or public.bvm_is_workshop_member(taller_id)
    )
  )
);

drop policy if exists retazos_write_scope on public.retazos;
create policy retazos_write_scope
on public.retazos for all
to authenticated
using (
  (taller_id is null and user_id = auth.uid())
  or (
    taller_id is not null
    and (
      public.bvm_is_workshop_owner(taller_id)
      or public.bvm_is_workshop_member(taller_id)
    )
  )
)
with check (
  user_id = auth.uid()
  and (
    taller_id is null
    or public.bvm_is_workshop_owner(taller_id)
    or public.bvm_is_workshop_member(taller_id)
  )
);
