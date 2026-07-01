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

