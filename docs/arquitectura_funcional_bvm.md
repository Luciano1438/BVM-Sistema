# BVM - Arquitectura funcional industrial

## Objetivo

BVM debe evolucionar de cotizador a sistema de fabricacion asistida para carpinterias.
La meta no es dibujar muebles desde cero, sino industrializar decisiones de taller:

- elegir una receta de modulo;
- configurar medidas y opciones;
- generar despiece con BRS/BKS;
- presupuestar con costos controlados;
- producir piezas identificables;
- imprimir etiquetas;
- asistir el armado por QR.

## Principio de producto

El usuario no empieza con un CAD vacio. Empieza con una receta.

Flujo recomendado:

1. Biblioteca de modulos.
2. Configuracion guiada.
3. Ingenieria generada.
4. Presupuesto y orden de fabricacion.
5. Etiquetas y trazabilidad por pieza.
6. Asistente de armado por QR.

## Modulos iniciales

La primera version industrial debe limitarse a los modulos que BVM ya entiende:

- Bajo mesada.
- Alacena.
- Placard.
- Cajonera.

La biblioteca puede crecer cuando el BRS/BKS de Ariel este listo para nuevas recetas.

## Entidades de datos

### proyecto

Representa una obra o pedido del cliente.

- id
- taller_id
- cliente
- estado
- fecha_creacion
- creado_por
- fecha_ultima_edicion
- editado_por

### modulo

Representa una receta configurada dentro del proyecto.

- id
- proyecto_id
- codigo_modulo
- tipo_modulo
- nombre
- version
- parametros_json
- precio_final
- estado

### pieza

Representa una pieza fabricable generada por el BRS.

- id
- modulo_id
- codigo_pieza
- nombre
- material
- largo
- ancho
- espesor
- cantidad
- veta
- tapacantos_json
- mecanizados_json
- cara_visible
- orientacion_armado
- orden_armado

### etiqueta

Representa el vinculo impreso con la pieza fisica.

- id
- pieza_id
- codigo_qr
- url_qr
- version
- fecha_impresion

## Codigo unico de pieza

Formato recomendado:

```text
BV-M001-LT-01-V1
```

Significado:

- BV: Buenavista.
- M001: modulo.
- LT: tipo de pieza, por ejemplo lateral.
- 01: numero dentro del modulo.
- V1: version.

Este codigo debe aparecer en:

- etiqueta;
- lista de corte;
- DXF;
- CSV para Aspire;
- optimizacion;
- presupuesto;
- pantalla de armado.

## QR

El QR no debe guardar toda la informacion. Debe guardar un ID o URL estable:

```text
/pieza/BV-M001-LT-01-V1
```

Al escanearlo, BVM consulta Supabase y muestra:

- modulo completo;
- pieza resaltada;
- medidas;
- material;
- veta;
- tapacantos;
- mecanizados;
- cara visible;
- piezas con las que se une;
- paso siguiente de armado.

Ventaja: si se corrige una instruccion, no hay que reimprimir la etiqueta.

## UX objetivo

Pantalla 1: Biblioteca

- tarjetas compactas por modulo;
- filtros por familia;
- no hay CAD vacio;
- se elige una receta.

Pantalla 2: Configuracion

- panel izquierdo: vista del modulo;
- panel derecho: medidas, material, herrajes y opciones;
- controles agrupados por decision real de taller;
- validaciones BKS visibles como alertas operativas.

Pantalla 3: Ingenieria

- tabla de piezas;
- seleccion de pieza;
- pieza resaltada en vista;
- tapacantos y mecanizados;
- costos visibles solo para dueño.

Pantalla 4: Produccion

- exportar lista de corte;
- exportar DXF/CSV;
- generar etiquetas PDF;
- ver orden de armado.

## Fases de implementacion

### Fase 1 - Estabilizacion

- separar calculo de UI;
- cachear despiece y vistas;
- bajar llamadas innecesarias a Supabase;
- consolidar modelos de datos;
- limpiar textos y encoding.

### Fase 2 - Proyecto/modulo/pieza

- crear tablas proyecto, modulo y pieza;
- persistir despiece estructurado;
- versionar piezas;
- separar presupuesto de produccion.

### Fase 3 - Etiquetas

- generar codigo unico por pieza;
- generar PDF de etiquetas;
- generar QR por pieza;
- pantalla de consulta por pieza.

### Fase 4 - Asistente de armado

- vista de pieza resaltada;
- orden de armado;
- instrucciones BKS;
- observaciones del taller.

### Fase 5 - 3D

- incorporar vista 3D solo cuando la base de piezas este estable;
- empezar con representacion simple;
- avanzar a Three.js si aporta valor real.

## Decision tecnica

Streamlit sigue sirviendo para MVP industrial y backoffice. Para una experiencia final mas fluida, BVM deberia evolucionar a:

- motor BRS/BKS en Python puro;
- Supabase como fuente de verdad;
- API/RPC para operaciones criticas;
- frontend mas especializado cuando el flujo este validado.

La prioridad ahora es no agregar complejidad visual antes de ordenar datos y trazabilidad.
