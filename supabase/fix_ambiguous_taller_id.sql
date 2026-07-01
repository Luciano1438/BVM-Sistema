-- Fix para error:
-- column reference "taller_id" is ambiguous
--
-- Ejecutar en Supabase SQL Editor.
-- El problema aparece cuando una funcion/policy usa un parametro llamado
-- taller_id igual que una columna. Usamos nombres p_* y columnas calificadas.

create or replace function public.es_miembro_taller(p_taller_id uuid)
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

create or replace function public.es_dueno_taller(p_taller_id uuid)
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

create or replace function public.buscar_usuario_por_email(p_email text)
returns uuid
language sql
stable
security definer
set search_path = public
as $$
  select p.id
  from public.perfiles p
  where lower(p.email) = lower(trim(p_email))
  limit 1;
$$;

grant execute on function public.es_miembro_taller(uuid) to authenticated;
grant execute on function public.es_dueno_taller(uuid) to authenticated;
grant execute on function public.buscar_usuario_por_email(text) to authenticated;

