
# DTF Control ROI

Sistema web en Python/Streamlit para controlar ventas diarias de impresión DTF, costos, reparto 50/50 entre socios y recuperación del equipo.

## Primer acceso

- Usuario: `admin`
- Clave: `admin123`

Cambia la clave desde el módulo Usuarios apenas entres.

## Fórmula del sistema

- Venta bruta = metros vendidos × precio por metro
- Costo producción = metros vendidos × costo por metro
- Utilidad bruta = venta bruta - costo producción
- Apartado ROI = utilidad bruta × % configurado para recuperar equipo
- Utilidad a repartir = utilidad bruta - apartado ROI
- Cada socio = utilidad a repartir / 2

## Ejecutar local

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Railway

Archivos incluidos:

- `app.py`
- `requirements.txt`
- `railway.json`

En Railway puedes usar SQLite para pruebas, pero para producción se recomienda agregar PostgreSQL o un volumen persistente.
Si agregas PostgreSQL, Railway colocará `DATABASE_URL` y el sistema lo usará automáticamente.

## Roles

- admin: ve todo, crea usuarios, cambia configuración y elimina ventas.
- socio: ve dashboard, informes y ROI.
- empleada: puede cargar ventas diarias y ver módulos básicos.


## Nuevos módulos Fix2

### Gastos del equipo

Permite cargar gastos deducibles del plotter:

- servicio técnico
- cabezal
- repuestos
- mantenimiento
- otros gastos del equipo

Estos gastos se descuentan del corte mensual antes de calcular ROI y reparto entre socios.

### Cuenta Javier

Permite controlar:

- deuda acumulada inicial previa al sistema
- abonos realizados a Javier
- plataforma de pago
- referencia
- notas
- saldo actual pendiente

### Cierre mensual

Cuando cierras un mes, el sistema calcula lo que le toca a Javier en ese corte y lo suma a su cuenta corriente. Esto evita duplicar cortes y mantiene el histórico de deuda, abonos y saldo.


## Fix3 - Abonos editables

En el módulo Cuenta Javier ahora existen tres pestañas:

- Registrar abono
- Editar abono
- Eliminar abono

Esto permite corregir fecha, monto, plataforma, referencia o notas cuando un pago fue cargado con error.


## Fix4 - Compatibilidad Streamlit 2026 y edición de abonos

- Se reemplazó `use_container_width=True` por `width="stretch"`.
- Se corrigió la edición de abonos para que al seleccionar un abono diferente se carguen automáticamente sus datos en los campos.
- Se actualizó `requirements.txt` a `streamlit>=1.50.0,<2.0.0`.


## Fix5 - Exportador PDF de Cuenta Javier

En el módulo Cuenta Javier se agregó el botón:

- Descargar estado de cuenta PDF

El PDF incluye:

- deuda acumulada inicial
- cortes mensuales cargados
- abonos registrados
- saldo actual pendiente
- referencias y notas de pagos
