# Llevar el modelo a una página web (se ve en el celular)

Lo que ya está listo en esta carpeta (no borra nada de lo que tenías):

- `publicar_web.py` copia el último reporte a la carpeta `docs/` (la página). Se ejecuta solo al final de `semana_nfl.py`. Cada corrida guarda además una copia con fecha en `docs/archivo/`, así un reporte nuevo **ya no pisa** al anterior en la página.
- `workflow_reporte.yml` (la receta de la nube; ver el paso 6) le dice a GitHub que corra el modelo solo (martes, jueves, sábado y domingo, 9:17 am de CDMX), publique la página y guarde la base de datos para la siguiente vez.
- `.gitignore` evita subir tu base de datos, tus reportes y tus archivos de datos.

Tu forma de usar el modelo en la laptop (IDLE, F5) sigue igual; ahora además crea la carpeta `docs/`.

## Pasos (una sola vez, ~20 minutos)

1. Crea una cuenta gratis en github.com.
2. Instala **GitHub Desktop** (desktop.github.com) e inicia sesión.
3. En GitHub Desktop: *File > Add local repository* y elige la carpeta `nfl_model`. Si te dice que no es un repositorio, pulsa «create a repository».
4. Revisa la lista de archivos a subir: **no** deben aparecer `data/`, `outputs/`, `reportes/` ni `historial/` (el `.gitignore` los excluye). **Nunca subas `data/odds_api_key.txt`** si lo usas.
5. *Publish repository*. Elige **público** si quieres usar las páginas gratis de GitHub (ver abajo la nota de privacidad).
6. Por seguridad, Windows no me deja crear la carpeta oculta `.github`, así que ese archivo lo agregas tú en la página de GitHub: en tu repositorio pulsa *Add file > Create new file*, en el nombre escribe `.github/workflows/reporte.yml` (las barras crean las carpetas), pega todo el contenido de `workflow_reporte.yml` y pulsa *Commit changes*.
7. En GitHub, en el repositorio: *Settings > Pages > Source: GitHub Actions*.
8. Pestaña *Actions > Reporte NFL > Run workflow*. La primera vez tarda unos 15 a 25 minutos porque descarga todo desde cero y vuelve a evaluar los props.
9. Al terminar, la dirección de la página aparece en esa misma ejecución (y en Settings > Pages). Ábrela en el celular y agrégala a tu pantalla de inicio.

## Privacidad

- En el plan gratis, una página de GitHub Pages es **pública** y el repositorio también (código y reporte). El reporte no tiene datos personales, pero cualquiera con el enlace lo ve.
- Si lo quieres privado: Cloudflare Pages permite poner acceso con correo gratis; el mismo workflow sirve cambiando el último paso. Dime y lo adapto.

## Qué puede fallar

- Kalshi, ESPN, Ourlads o rbsdm podrían bloquear a los servidores de GitHub. Si pasa, el modelo corre sin esas fuentes y el reporte lo avisa. No lo he podido probar desde aquí.
- El historial acumulado de tu laptop (líneas, predicciones, props) no se sube; en la nube empieza desde cero y se va llenando con cada corrida.
- Los horarios de GitHub se corren a veces unos minutos.

## Cómo está armada la página (rediseño de la Entrega 3)

- `docs/index.html` es solo la «carcasa» (portada, menú y navegación, ~240 KB). Cada sección pesada vive en `docs/f/<nombre>.<huella>.html` y se descarga **solo cuando la abres** (por eso el celular abre la portada en menos de 1 s). No hay que hacer nada: `semana_nfl.py` / `publicar_web.py` los genera y borra los fragmentos viejos.
- `reportes/reporte_*.html` sigue siendo **un solo archivo completo** que funciona con doble clic (sin servidor).
- Para revisar la página en Windows antes de subirla: abre una terminal en la carpeta `docs` y ejecuta `py -m http.server 8000`; entra a http://localhost:8000. (Abrir `docs/index.html` con doble clic no carga los fragmentos porque el navegador bloquea `fetch` en `file://`.)
- Todos los colores y tamaños salen de un solo archivo: `ui/tokens.css`. Para cambiar el tema o el tamaño de letra se edita ahí.
- Direcciones directas (se pueden guardar o compartir): `#partido=TB-DET&tab=apuestas` (`apuestas`, `puntos`, `props`, `matchup`), `#tab=calidad`, `#tab=jugadores`, `#tab=proyecciones`, `#tab=guia`.


## Actualización: la página ya NO necesita servidor local
Los fragmentos de `docs/f/` ahora son archivos `.js` (se cargan con `<script src>`), así que `docs/index.html` funciona con doble clic y también en GitHub Pages. Ya no hace falta `py -m http.server`. Si una sección dice «No pude cargar esta parte», revisa que la carpeta `f` esté junto a `index.html` y pulsa «reintentar».
