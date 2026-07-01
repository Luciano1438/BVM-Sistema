-- Reglas BVM: datos personales vs datos del taller.
-- Ejecutar en Supabase SQL Editor si alguna columna falta.
-- No migra datos personales del colaborador invitado.

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

-- Si el dueño crea un taller, sus datos viejos pueden asociarse al taller
-- desde la app. No hacer esto para colaboradores.

-- Migracion puntual para talleres ya creados:
-- comparte con el taller solo los datos personales viejos del dueño.
-- No toca presupuestos/precios/retazos personales de colaboradores.
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

-- La app respeta la constraint existente unique_user_clave:
-- un dueño tiene una sola fila por clave, sea personal o compartida.
-- Al entrar a un taller, esa misma fila se asocia con taller_id.

update public.retazos r
set taller_id = t.id
from public.talleres t
where r.taller_id is null
  and r.user_id = t.owner_id;

-- Policies RLS para compartir dentro del taller sin exponer historiales personales.
alter table public.ventas enable row level security;
alter table public.configuracion enable row level security;
alter table public.retazos enable row level security;

drop policy if exists ventas_select_scope on public.ventas;
create policy ventas_select_scope
on public.ventas for select
to authenticated
using (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = ventas.taller_id
        and mt.user_id = auth.uid()
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
    or exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = ventas.taller_id
        and mt.user_id = auth.uid()
    )
  )
);

drop policy if exists ventas_update_scope on public.ventas;
create policy ventas_update_scope
on public.ventas for update
to authenticated
using (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = ventas.taller_id
        and mt.user_id = auth.uid()
    )
  )
)
with check (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = ventas.taller_id
        and mt.user_id = auth.uid()
    )
  )
);

-- Guardado robusto de precios/configuracion desde Streamlit.
-- Evita conflictos con la constraint existente unique_user_clave.
create or replace function public.guardar_configuracion_bvm(
  p_clave text,
  p_valor double precision,
  p_categoria text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_taller_id uuid;
  v_owner_id uuid;
begin
  if v_uid is null then
    raise exception 'Usuario no autenticado';
  end if;

  select mt.taller_id
    into v_taller_id
  from public.miembros_taller mt
  where mt.user_id = v_uid
  limit 1;

  if v_taller_id is null then
    select t.id
      into v_taller_id
    from public.talleres t
    where t.owner_id = v_uid
    limit 1;
  end if;

  if v_taller_id is not null then
    select t.owner_id
      into v_owner_id
    from public.talleres t
    where t.id = v_taller_id;

    if v_owner_id is distinct from v_uid then
      raise exception 'Solo el dueño del taller puede modificar precios';
    end if;
  else
    v_owner_id := v_uid;
  end if;

  update public.configuracion c
  set valor = p_valor,
      categoria = p_categoria,
      taller_id = v_taller_id
  where c.user_id = v_owner_id
    and c.clave = p_clave;

  if not found then
    insert into public.configuracion (user_id, taller_id, clave, valor, categoria)
    values (v_owner_id, v_taller_id, p_clave, p_valor, p_categoria);
  end if;
end;
$$;

grant execute on function public.guardar_configuracion_bvm(text, double precision, text) to authenticated;

-- Version explicita: la app manda owner_id/taller_id ya resueltos.
-- Evita que la funcion guarde en una fila personal cuando el taller existe.
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
      raise exception 'Solo el dueño del taller puede modificar precios';
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

drop policy if exists ventas_delete_scope on public.ventas;
create policy ventas_delete_scope
on public.ventas for delete
to authenticated
using (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = ventas.taller_id
        and mt.user_id = auth.uid()
    )
  )
);

drop policy if exists configuracion_select_scope on public.configuracion;
create policy configuracion_select_scope
on public.configuracion for select
to authenticated
using (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = configuracion.taller_id
        and mt.user_id = auth.uid()
    )
  )
);

drop policy if exists configuracion_write_scope on public.configuracion;
create policy configuracion_write_scope
on public.configuracion for all
to authenticated
using (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = configuracion.taller_id
        and mt.user_id = auth.uid()
        and mt.rol = 'dueño'
    )
  )
)
with check (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = configuracion.taller_id
        and mt.user_id = auth.uid()
        and mt.rol = 'dueño'
    )
  )
);

drop policy if exists retazos_select_scope on public.retazos;
create policy retazos_select_scope
on public.retazos for select
to authenticated
using (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = retazos.taller_id
        and mt.user_id = auth.uid()
    )
  )
);

drop policy if exists retazos_write_scope on public.retazos;
create policy retazos_write_scope
on public.retazos for all
to authenticated
using (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = retazos.taller_id
        and mt.user_id = auth.uid()
    )
  )
)
with check (
  user_id = auth.uid()
  or (
    taller_id is not null
    and exists (
      select 1
      from public.miembros_taller mt
      where mt.taller_id = retazos.taller_id
        and mt.user_id = auth.uid()
    )
  )
);
