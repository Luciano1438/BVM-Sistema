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

update public.retazos r
set taller_id = t.id
from public.talleres t
where r.taller_id is null
  and r.user_id = t.owner_id;
