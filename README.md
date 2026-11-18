# Modelo NFL: equipos (ganador, spread, totales) + props de jugadores + matchups

Estima la probabilidad de cada resultado, la compara con la probabilidad que exige la cuota y te dice dónde hay **ventaja** (= probabilidad del modelo − probabilidad que exige la cuota). Datos de [nflverse](https://github.com/nflverse/nflverse-data) (calendario con líneas de mercado y play-by-play desde 1999): gratis y sin API key.

## Uso semanal (IDLE)

1. Instala Python desde python.org (incluye IDLE) y descomprime esta carpeta. **Todos los archivos deben quedarse juntos.**
2. Abre **`semana_nfl.py`** con IDLE (clic derecho → *Edit with IDLE*) y pulsa **F5** (*Run → Run Module*).
3. La primera vez instala los paquetes que falten y descarga los datos (1-2 minutos). Después tarda mucho menos.
4. Se abre en tu navegador el **reporte de la semana** (carpeta `reportes/`) y se guarda un CSV en `outputs/`.

Repite el paso 2 cada semana (o cada día: las líneas cambian). Al inicio de `semana_nfl.py` puedes cambiar `SEMANA` (None = la próxima con partidos pendientes), `UMBRAL_VENTAJA` (0.02 = 2 puntos de probabilidad) y `ACTUALIZAR_DATOS` (False = sin internet). Si no hay internet, usa lo último descargado.

Cada ejecución guarda las predicciones en `historial/`; cuando se juegan los partidos, el reporte muestra cómo le fue en semanas anteriores.

## Qué trae el reporte

- **Resumen** de qué apuestas (si hay) superan el umbral de valor.
- **Cómo leer el reporte:** qué hace cada modelo y glosario de cada número (línea, margen, cuota, ventaja…).
- **Gráficos:** margen esperado (mercado vs modelo A vs modelo B), probabilidad de ganar (modelo vs mercado) y ventaja por partido y tipo de apuesta.
- **Touchdowns** (sección 4): los 20 jugadores con más probabilidad de anotar en la semana y, dentro de **cada partido**, la lista completa de quién tiene más probabilidad de anotar.
- **Props destacados** de la semana (sección 5) y, dentro de cada partido, **matchups** y **props por jugador** con % de superar la línea e historial de la temporada pasada (ver más abajo).
- **Detalle partido por partido** en palabras. Cada mercado siempre muestra un veredicto: *Posible valor*, *Sin ventaja clara*, *Sin ventaja* o *Sin cuota publicada*; nunca queda vacío.
- **Fiabilidad histórica** (calibración y error frente al mercado) y **resultados de semanas anteriores**.

## Touchdowns y «¿cubrió la línea?» (nuevo)

**Probabilidad de anotar.** Para cada jugador (QB, RB, WR, TE) de cada partido, el modelo calcula la probabilidad de anotar **al menos un TD por tierra o por recepción** (el TD de pase no cuenta, igual que en el mercado «anytime TD»). Usa lo mismo que los demás props: su ritmo reciente de TD y de uso, los puntos que se espera anote su equipo, el rival y la localía. En cada partido del reporte aparece la lista **completa** ordenada de más a menos probable, con la **cuota justa** (sin comisión) y una calculadora: escribes la cuota de tu casa y te dice si paga más de lo que vale.
- Probado con 24 711 jugador-partidos de 2021-2025 (cada año predicho solo con años anteriores): **bien calibrado** (cuando dice 35 % anota ~35 %; el 10 % con mayor probabilidad anotó 47 % vs 48 % esperado) y reduce el error de probabilidad (log-loss) 4 % frente al simple promedio reciente (0.486 vs 0.505).
- Probé añadir uso en zona roja (acarreos y targets dentro de la yarda 20 y 5, del play-by-play) y **no mejoró nada**, así que no se incluyó.
- Las cuotas «anytime TD» llevan 7-10 % de comisión: la calculadora exige ≥ 3 puntos de diferencia. Es un mercado de mucho azar; que algo tenga «valor» no lo hace seguro.
- También se guarda en `outputs/touchdowns_<temporada>_semana<N>.csv` (todos los jugadores, por partido, con historial local/visita).

**Historial de cobertura (temporada pasada y actual).** Para cada jugador-partido de 2025 y 2026 se revisa si **superó su línea o no**, y se separa **de local / de visita** (tabla `props_cobertura`, vista `v_cobertura_jugador`). En el reporte, cada jugador muestra por ejemplo: `2025: 9/17 (53 %) · local 5/8 · visita 4/9`, con en negritas lo que corresponde al partido de hoy, y al lado la tasa de la liga para ese mercado como referencia (p. ej. en yardas de recepción solo ~39 % de los jugadores supera su línea «normal»).
- **Importante: no son líneas reales de casas de apuestas.** Las líneas históricas de props no son gratuitas. La línea de cada partido se reconstruye con información previa a ese partido (modelo que solo ve el historial del jugador, entrenado con temporadas anteriores; nunca con el propio partido). En touchdowns la línea es siempre 0.5, así que ahí el resultado es exacto.
- Si tienes líneas reales (de tu casa), guárdalas en `data/lineas_props.csv` con las columnas `temporada,semana,jugador,mercado,linea` (mercado: `pass_yds, pass_cmp, pass_td, pass_int, rush_yds, rush_att, rec_yds, rec, tgt`) y se usarán en lugar de la línea normal donde coincidan; el empate exacto se descarta.
- Incluye playoffs de 2025. Los jugadores rinden un poco más de local en pases/yardas/acarreos, pero la diferencia es chica (se muestra en la sección «¿Rinden más de local que de visita?»).

## Líneas automáticas de Kalshi y casas (nuevo)

Ya no tienes que escribir la línea: en cada ejecución el modelo **lee solo los precios de Kalshi** (API pública de solo lectura, sin cuenta ni llave) para yardas de pase/tierra/recepción, pases completos, recepciones, acarreos, TD de pase, intercepciones y «anotar 1+ TD».
- Kalshi publica «escaleras» por jugador (40+, 50+, 60+ yardas…). El precio es una probabilidad (60¢ = 60 %). Comprar «Sí» cuesta el *ask*; comprar «No» cuesta 1 − *bid*.
- En el reporte: (1) las casillas **«Tu línea y cuotas»** y **«Tu cuota»** de los TD ya vienen llenas con el escalón más cercano al 50 % y sus cuotas equivalentes (con la comisión de Kalshi ≈ 7 % × precio × (1 − precio)); (2) la sección **«Líneas de Kalshi vs modelo»** muestra los escalones donde el modelo ve más de 3 puntos de ventaja neta, y cada partido trae su propia lista; (3) se guarda `outputs/valor_kalshi_<temporada>_semana<N>.csv` y la tabla `lineas_casas` de la base.
- Solo se usan precios con diferencia compra-venta ≤ 10¢. **Kalshi tiene poca liquidez** en props: el precio puede no estar disponible en cantidad.
- Si el modelo y el mercado discrepan mucho, lo más probable es que el mercado sepa algo que el modelo no (lesión, rol, clima). Úsalo como segunda opinión, no como apuesta segura.
- **DraftKings:** no tiene API pública y su página no se «raspa». Si quieres sus líneas, crea una llave gratuita en [The Odds API](https://the-odds-api.com), guárdala (solo el texto) en `data/odds_api_key.txt` y el modelo la usará para leer DraftKings. Esa parte sigue la documentación del servicio pero **no está probada con datos reales**; cada ejecución gasta créditos de tu plan (≈ 9 mercados por partido).

> Detalle: si el modelo y Kalshi difieren en más de 10 puntos (mediana por jugador y mercado), el jugador se marca como «discrepancia de información» y no se autollena ni aparece en las listas de valor. Los QB que Kalshi lista para un partido tienen prioridad sobre el depth chart.

## Lesionados automáticos (ESPN) y ajuste por bajas (nuevo)

- **Fuente:** `lesiones_espn.py` lee el JSON abierto de ESPN (`site.api.espn.com/apis/site/v2/sports/football/nfl/injuries`, sin llave): los 32 equipos, con estatus, tipo de lesión, fecha de regreso y nota del reporte. Se guarda en la tabla `lesiones_espn` (una foto por día) y se actualiza si tiene más de 1 hora.
- **Por qué:** el reporte oficial (nflverse) llega por partes; el miércoles solo trae la práctica de unos cuantos jugadores. ESPN completa a quien el reporte oficial aún no marca (lo oficial siempre manda). Out / Injured Reserve → Out; Doubtful → Doubtful; Questionable → Questionable. Out y Doubtful no se proyectan.
- **Ajuste por bajas de compañeros:** el modelo de props ahora sabe cuánto uso esperado (targets, acarreos, intentos de pase) tenían los compañeros que jugaron el partido anterior y esta semana no están. En el historial (2016–2025), cuando falta un titular importante: un WR recibe ~0.6 targets más, un RB ~2.8 acarreos más si falta el RB1 y un QB suplente lanza ~30 yardas más que su promedio. La columna `ajuste_por_bajas_de_companeros_%` del CSV de props muestra cuánto cambió cada proyección por eso.
- **Límites:** solo cuentan las bajas *nuevas* (jugó el partido anterior y hoy no); en las bajas largas el promedio reciente ya se adaptó. Un QB suplente sin historial no se proyecta. La mejora medida en las pruebas es pequeña y concentrada en esos casos (completos de pase, acarreos y yardas de pase). Es una segunda opinión, no asesoría financiera.

## ¿Le gana el modelo al mercado? (nuevo)

`evaluar_mercado.py` (ábrelo en IDLE y pulsa F5) compara, partido por partido, la probabilidad del modelo con el **precio de Kalshi justo antes del inicio** y con lo que pasó de verdad. Crea `reportes/modelo_vs_mercado.html` con: error por tipo de apuesta (Brier), calibración, cuánto pesa cada uno, apuestas simuladas con intervalo de confianza, movimiento del precio (CLV) y si el precio tiene sesgo por tramos.

- **Datos:** `kalshi_historial.py` baja de la API pública de Kalshi los mercados de props ya liquidados y sus precios por hora (guardados en `data/kalshi_hist.db`). La primera vez tarda (decenas de miles de consultas, ~1 hora; se puede interrumpir y reanuda); después solo baja las semanas nuevas.
- **Sin trampa de información:** el modelo de cada temporada se entrena solo con temporadas anteriores, y de cada jugador se compara un solo escalón: el del medio de la escalera publicada antes del partido (elegir por volumen sesgaría la muestra, porque en pleno partido se opera más en los escalones que se cumplen).
- **Cómo leerlo:** si el intervalo de «modelo − mercado» incluye el cero, no se puede distinguir del mercado. Si el modelo tiene peso casi cero en la regresión, una vez conocido el precio casi no agrega información.

### El precio de Kalshi como punto de partida (nuevo)

Como el precio le ganó al modelo, el reporte semanal ya no trata «modelo − precio» como ventaja. La probabilidad de trabajo es **80 % precio de Kalshi + 20 % modelo** (10 % en acarreos y yardas por tierra; `PESO_MODELO` en `lineas_casas.py`), y la ventaja neta se calcula con esa mezcla y descontando la comisión. Validación cruzada (por semana y por temporada): 15–25 % fueron los pesos más estables; pesos ajustados por mercado o más altos (35 %+) no mejoraron o empeoraron fuera de muestra. La mejora total es mínima (≈ −0.0003 de Brier, intervalo que roza el cero), así que **casi nunca verás «ventaja»: es lo esperado**. El CSV conserva `ventaja_solo_modelo_pts` por si quieres ver la diferencia cruda. Jugadores sin precio en Kalshi siguen usando solo el modelo.

### Probabilidad de jugar (nuevo)

Antes un jugador «Questionable» se proyectaba como si fuera a jugar seguro. Ahora `prob_jugar.py` estima **cuántos juegan según su práctica de la semana** (medido con 2016–2025 de nflverse, jugadores habituales): sin practicar ≈ 42 %, práctica limitada ≈ 69 %, completa ≈ 86 % (varía algo por posición). Validado fuera de muestra (2019–2025): error Brier 0.345 (juega seguro) → 0.227 (tasa única) → **0.212** (práctica + posición). Si juegan rinden algo menos (receptores/corredores −4 a −8 %, QB igual); esa baja ya está en la proyección «si juega».

- En el reporte aparece la etiqueta «juega ~X %» junto al jugador; la tabla de proyecciones es **condicional a que juegue** (así pagan las casas tradicionales, que anulan la apuesta si no juega).
- En **Kalshi** el «Sí» pierde si no juega, así que la comparación con Kalshi y las calculadoras con línea automática multiplican por esa probabilidad.
- El CSV trae `prob_de_jugar_%`. Out y Doubtful siguen fuera de las proyecciones. `evaluar_prob_jugar.py` repite la validación.
- ESPN y Ourlads no dan práctica: para esos jugadores se usa el promedio de los tres casos.

### Jugadores sin historial: novatos y suplentes (nuevo)

Antes, quien tenía menos de 2 partidos (o ninguno) no se proyectaba, y si el titular estaba fuera el equipo podía quedarse sin QB o usar a un tercer QB. Ahora `sin_historial.py`:
- **Agrega a los jugadores del depth chart sin estadísticas** (novatos, practice squad que sube) y deja entrar a quien tiene 0–1 partidos si tiene un rol (QB 1–2, RB 1–3, WR 1–4, TE 1–2). El QB que se proyecta sigue a Ourlads/Kalshi y, si no hay dato, al depth chart.
- **QB:** se mantiene el promedio de la posición que ya usaba el modelo y se mezcla 50/50 con el promedio de los QB debutantes de su ronda del draft (R1, R2–3, R4–7, sin draft). Medido fuera de muestra (113 arranques con <2 partidos, 2017–2025): error de ~62 yardas por pase y rango 10–90 % que cubre 73–86 % de los casos, así que no se ensancha la dispersión. Es una estimación honesta, no precisa: un QB debutante se equivoca ~60 yardas por partido.
- **RB/WR/TE con poco historial:** se les asigna el uso promedio de su lugar en el depth chart (titular, segundo…) recortado 15 % y se ensancha 30 % su dispersión. **Esta parte no se pudo validar** (no hay depth charts históricos limpios): tómala como referencia.
- El reporte los marca con «sin historial» / «1 partido previo»; el CSV trae `partidos_previos`. Nunca aparecen en «props destacados».

### Correlaciones y combinadas (nuevo)

Cada jugador se modela solo, pero los resultados de un mismo partido se mueven juntos. `correlaciones.py` mide cuánto (residuos fuera de muestra 2021–2026, ~2 millones de pares) y calcula la **probabilidad conjunta** de una combinada con una cópula gaussiana (cada apuesta conserva su probabilidad; solo cambia cómo se combinan).

- **Hallazgos (estables entre 2021–23 y 2024–26):** QB con sus propios receptores +0.13 a +0.19 (yardas con yardas); receptores del mismo equipo entre sí ≈ 0; QB contra el QB rival +0.13; mismo jugador en otro mercado: recepciones–yardas ≈ 0.8, acarreos–yardas ≈ 0.83, pases completos–yardas ≈ 0.9, yardas–TD 0.2–0.3.
- **Validación:** con correlaciones de 2021–23 aplicadas a 2024–26, «ambos sobre lo esperado» ocurrió 29.0 % de las veces; independencia predice 25 %, la cópula 28.6 % (error Brier 0.2076 → 0.2037, intervalo que no incluye el cero).
- **En el reporte:** cada jugador tiene una casilla; al marcar 2 o más aparece abajo el panel «Combinada» con la probabilidad si fueran independientes, la probabilidad con la correlación, la cuota justa y un cuadro para escribir la cuota que te pagan. El lado (OVER/UNDER, Sí/No) se cambia con el botón de cada jugador; apuestas de partidos distintos se tratan como independientes.
- Ojo: la correlación es modesta (una combinada QB + receptor sube ~+14 % relativo) y muchas casas ya ajustan sus combinadas del mismo partido. `actualizar_correlaciones.py` recalcula la tabla (3–6 min).

### Variables de rol: snaps, cuota de acarreos, descanso (nuevo)

El modelo solo miraba promedios de estadísticas. Ahora también ve el **rol**: % de snaps ofensivos (promedio reciente, último partido y tendencia; de `snap_counts` de nflverse, desde 2013), **cuota de acarreos del equipo**, días de descanso del equipo y si el jugador venía de faltar a partidos. Todo calculado solo con partidos anteriores (verifiqué que no hay fuga de información).

Fuera de muestra 2021–2026 (entrenando con temporadas previas), todas las mejoras tienen intervalo que no incluye el cero: error de yardas por pase **−7 %**, pases completos **−7.5 %**, acarreos **−5.5 %**, yardas por tierra −3 %, receptores −1 a −2 %, TD −0.6 %. Contra los precios de Kalshi (misma muestra de 321 partidos): la diferencia de error modelo − mercado bajó de +0.0081 a +0.0055 (en acarreos de 0.286 a 0.262 frente a 0.240 del mercado) y la mezcla con el precio mejora un poco más. **El precio sigue ganando**, pero por menos.
La primera vez que corres baja los snaps (14 archivos pequeños) y la evaluación de props se recalcula una vez (2–4 min, `props_eval_v4.json`).

### Mis apuestas: registro, resultados y CLV (nuevo)

`mis_apuestas.py` (ábrelo en IDLE y pulsa F5) mide con **tu dinero** si el método funciona:
1. **Registrar:** en el reporte semanal, escribe tu línea y tu cuota en la fila del jugador; junto al resultado aparece el botón **«copiar OVER / UNDER»** (en touchdowns, «copiar Sí»). Luego, en `mis_apuestas.py`, elige la opción 1: pega lo copiado y te pide monto y casa. También puedes registrar a mano (opción 2) o editar `data/mis_apuestas.csv` en Excel.
2. **Liquidar:** automático con los resultados reales (jugadores: estadísticas y snaps de nflverse; ganador, handicap y total: marcador). Empates y jugadores que no juegan se anulan; en Kalshi, si el jugador no juega el «Sí» pierde. Cuotas aceptadas: americana (+150, −110), decimal (2.5) o precio de Kalshi (44c; incluye su comisión).
3. **Reporte `reportes/mis_apuestas.html`:** ganancia, **ROI con su intervalo de incertidumbre**, acierto real vs el que implican los precios, calibración del modelo (Brier vs precio), ganancia acumulada, desglose por tipo y mercado, y **CLV** (si apostaste a mejor precio que el cierre).
- **Ojo con la suerte:** para distinguir un ROI verdadero de +3 % del azar hacen falta unas 3,000 apuestas; por eso el reporte destaca el CLV y la calibración, que se estabilizan mucho antes.
- El CLV se calcula con el cierre del propio partido (ganador: moneyline de cierre; handicap y total: línea de cierre; jugadores: la «cuota de cierre» que escribas, o el cierre de Kalshi si hay datos).

## Jugadores, props y matchups

Dentro de cada partido del reporte (clic en el partido) hay dos bloques nuevos:

**1. Matchup: cómo se enfrenta cada ataque a la defensa rival.** Para los dos lados del partido, con ranking de 32 equipos y una franja de «peor → mejor»:
juego aéreo y terrestre (EPA por jugada ajustado por rival), yardas por aire y por tierra que permite cada defensa (frente al promedio de la liga), **presión sobre el QB** (cuánto sufre el ataque vs cuánto genera la defensa) y **rendimiento contra el blitz** (EPA por dropback con y sin blitz, y cuánto blitzea la defensa). Cada fila tiene una etiqueta: *Favorable al ataque*, *Favorable a la defensa* o *Parejo*.

**2. Props de jugadores.** Por equipo: perfil de la temporada (QB: pases, % completos, yardas por partido; RB: acarreos, yardas por acarreo **y** targets/recepciones como receptor; WR/TE: targets por partido, recepciones, % atrapadas, yardas por partido y por recepción, target share) y una tabla de proyecciones con:
- **Proyección** de hoy (rival, guion del partido y clima incluidos) y **rango típico** (25-75 %).
- **Línea «normal»:** lo que se esperaría del jugador sin mirar este partido; el **% entre paréntesis** es cuánto lo mueve el contexto (rival, spread, total).
- **Tu línea y cuotas:** escribe la línea y las cuotas de tu casa de apuestas y la tabla calcula la probabilidad de over/under, la que exige la cuota y si hay ventaja. Sin línea escrita muestra «escribe la línea →» (nunca queda vacío sin explicación).

La sección **«Props destacados»** lista los jugadores donde el contexto más mueve la proyección frente a su línea normal, solo en mercados donde el backtest mostró señal (yardas y pases completos de QB, yardas y acarreos de RB). **Son candidatos, no apuestas confirmadas:** no hay forma gratuita de saber la línea real de tu casa; compárala con la tuya en la calculadora.

Reglas: no se proyecta a jugadores *Out* o *Doubtful* en el reporte de lesiones ni en Ourlads; se usa un QB por equipo (el titular del depth chart).

### De dónde salen los datos
Pediste pro-football-reference.com, rbsdm.com y ourlads.com. Desde este entorno no se podía acceder a esas páginas, y PFR prohíbe el scraping automatizado, así que se usaron los **mismos datos de origen vía nflverse** (gratis): estadísticas por jugador y semana, estadísticas avanzadas de PFR (presiones, blitz), charting de FTN (blitzers), play-by-play (la base de rbsdm.com: EPA), lesiones y depth charts (equivalente a Ourlads). Si prefieres usar esas páginas directamente, hazlo manualmente o con su licencia/API oficial.

### Qué tan confiable es (backtest de props)
Evaluado de forma cronológica (nunca ve el futuro). El modelo reduce el error medio absoluto frente al simple promedio reciente del jugador entre **1.6 % y 4.6 %** según el mercado (p. ej. yardas de pase: 66.0 vs 69.1; yardas de recepción: 21.7 vs 22.1). Es una mejora **modesta**: el pronóstico de props es ruidoso por naturaleza.
- No existen líneas históricas gratuitas de props, así que **no se puede medir ROI**; solo la precisión de la proyección y si el lado que apunta el contexto se cumple (en yardas de pase, el over marcado por el contexto salió 59 %, el under 68 %).
- Las probabilidades se encogen hacia 50 % en los mercados donde el backtest mostró exceso de confianza.
- Touchdowns, intercepciones y receptores de bajo volumen son los más impredecibles: úsalos con cautela.
- Las casas ya ajustan por rival y lesiones; no asumas ventaja sin comparar con la línea real.

### Primera ejecución
Si tu base venía de una versión anterior, la primera vez vuelve a bajar las estadísticas de jugadores (ahora con touchdowns; ~15 archivos pequeños, unos segundos). Descarga además estadísticas de jugadores, lesiones, charting y el depth chart (todo se guarda en `data/nfl.db`) (archivo grande, ~70 MB; se vuelve a bajar como máximo una vez cada 20 horas). La evaluación de props se guarda en `data/props_eval_v4.json` y se recalcula cada 30 días (puede tardar uno o dos minutos). Si algo de props/matchups falla, el reporte de equipos sigue funcionando y se imprime el aviso.

## Ourlads y rbsdm

Pediste usar pro-football-reference.com, rbsdm.com y ourlads.com. Estado real de cada una:

| Sitio | Estado | Qué se guarda en la base SQL |
|---|---|---|
| **ourlads.com** | Se descarga solo al correr `semana_nfl.py`: lee los 32 depth charts (HTML público, 1.5 s de pausa entre páginas) | `ourlads_depth`: QB/RB/WR/TE/FB por equipo y orden, con estado de disponibilidad (**O** fuera, **D** dudoso, **Q** cuestionable). Los *Out/Doubtful* no se proyectan, los *Q* llevan etiqueta, y el QB titular sale de aquí |
| **rbsdm.com** | Se descarga solo: la página carga sus tablas desde consultas JSON a su propio sitio y el modelo hace las mismas consultas (con tu autorización explícita) | `rbsdm_team_tiers` (EPA, wEPA y tasa de éxito por equipo, pase/carrera, ataque/defensa), `rbsdm_quarterbacks` (EPA/jugada, CPOE...), `rbsdm_pase_neutral`, `rbsdm_cuarto_down`, `rbsdm_suerte` (fumbles, 3ras y zona roja), `rbsdm_series` (éxito por serie ofensiva). Dentro de cada partido del reporte hay una tabla de referencia con EPA y éxito |
| **pro-football-reference.com** | **No se pudo:** Cloudflare muestra una verificación anti-bots y no se debe saltar (además su política prohíbe el scraping) | Sus estadísticas avanzadas (presiones, blitz) llegan vía nflverse, que redistribuye los mismos datos |

Cada lectura se guarda con su fecha (`capturado`), así que se acumula historial semana a semana. Las descargas son como máximo una vez cada 20 horas por sitio y con pausas; si un sitio no responde o bloquea la descarga automática, el modelo avisa y usa la última lectura guardada (y, si no hay ninguna, el reporte sigue funcionando con nflverse). También se guarda una copia de cada lectura como JSON en `fuentes_web/`; si copias ahí un archivo nuevo, se importa solo.

**Pendiente de probar en tu PC:** las dos descargas directas (Ourlads y rbsdm) no pude correrlas de punta a punta desde mi entorno (allá esos sitios están bloqueados). Sí probé que la lectura de cada formato coincide con lo que mostró el navegador y que la descarga se guarda bien con respuestas simuladas. Ourlads es un sitio de suscripción y rbsdm no publica una API oficial: revisa sus condiciones de uso; si cambian su formato, la descarga avisará y usará la última lectura. No se leen aún: `pass-over-expected` y los 4th downs jugada por jugada (piden una consulta por equipo).

## Base de datos SQL (nuevo)

Todos los datos viven ahora en una base **SQLite** (`data/nfl.db`): un solo archivo, sin instalar nada (Python ya trae SQLite). Cada vez que ejecutas `semana_nfl.py` (o `base_datos.py`) se **descarga lo nuevo y se guarda ahí**; el modelo lee siempre de la base. Las temporadas pasadas se bajan una sola vez; la temporada en curso se actualiza en cada ejecución. Sin internet, se usa lo guardado. Si venías de la versión anterior con CSV en `data/`, se migran solos a la base (no se vuelve a descargar).

| Tabla | Contenido |
|---|---|
| `games` | Calendario, resultados y líneas/cuotas de mercado desde 1999 |
| `team_games` | EPA por jugada (pase/carrera) de cada equipo en cada partido |
| `matchup_games` | Dropbacks, blitz y presión por equipo y partido |
| `player_weeks` | Estadísticas de QB/RB/WR/TE por semana (desde 2012) |
| `injuries`, `depth` | Reporte de lesiones y depth chart más reciente (nflverse) |
| `ourlads_depth`, `rbsdm_*` | Lecturas de Ourlads y rbsdm (ver sección anterior), una por fecha |
| `descargas` | Qué se descargó, de dónde y cuándo |
| `lineas_historial` | **Se llena sola:** cómo se movió la línea/cuotas de cada partido entre ejecuciones |
| `predicciones_modelo` | **Se llena sola:** lo que dijo el modelo cada día (margen, probabilidades, ventajas) |
| `props_proyecciones` | **Se llena sola:** la proyección de cada jugador y mercado cada día (incluye `p_td`, probabilidad de anotar) |
| `props_cobertura` | Por jugador-partido de la temporada pasada y la actual: línea, resultado, si la superó y si fue de local o visita |

Vistas listas para consultar: `v_jugador_temporada` (targets, recepciones, % atrapadas, yardas por partido y por recepción, acarreos, pases...), `v_defensa_permite` (yardas por aire y por tierra que permite cada defensa por partido), y las de seguimiento que se llenan al jugarse los partidos: `v_props_resultados` y `v_props_precision` (proyección del modelo vs promedio reciente vs lo que pasó de verdad) y `v_equipos_resultados` (modelo B vs mercado vs resultado real) y `v_cobertura_jugador` (por jugador y mercado: en cuántos partidos superó su línea, total / de local / de visita).

**Cómo consultarla:** abre `base_datos.py` en IDLE, escribe tu SQL en la variable `CONSULTA` y pulsa F5 (imprime el resultado y lo guarda en `outputs/consulta.csv`; trae ejemplos al final del archivo). También puedes abrir `data/nfl.db` con [DB Browser for SQLite](https://sqlitebrowser.org/) (gratis).

**Qué NO es:** la base se alimenta de nflverse (los mismos datos de origen que PFR/rbsdm/ourlads, pero no esas páginas). No guarda el play-by-play jugada por jugada (pesaría varios GB): guarda los resúmenes que usa el modelo. Lo más valioso a mediano plazo son las tablas de historial: con las semanas acumularás tu propio registro de líneas, predicciones y proyecciones para medir con datos reales qué tan bien acierta el modelo. Si quieres incorporar tablas que tú exportes de PFR (botón *Share & Export → Get table as CSV*), se pueden importar a la base.

## Los modelos, en simple

- **Mercado:** la línea y las cuotas de las casas. Ya incluyen lesiones y noticias. Es la referencia.
- **Modelo A (opinión independiente):** solo mira cómo juegan ambos equipos (ataque y defensa por pase y carrera, y puntos), ajustado por la dificultad de los rivales. No ve la línea, lesiones ni mariscales.
- **Modelo B (el de decisión):** parte de la línea y la corrige con los ratings de A y el descanso. Da las probabilidades del reporte: fue el más confiable en el historial.
- **Ventaja:** probabilidad del modelo − probabilidad que exige la cuota. Negativa = no conviene. Se marca «posible valor» con +2 pts o más.

## Archivos

| Archivo | Qué hace |
|---|---|
| `semana_nfl.py` | **El que abres en IDLE.** Actualiza datos, calcula y abre el reporte |
| `reporte.py` | Construye el reporte HTML con gráficos y explicaciones |
| `predict.py` | Probabilidades y ventajas de los partidos pendientes (también por consola) |
| `fuentes_web.py` | Descarga y guarda en la base las lecturas de Ourlads y rbsdm (`fuentes_web/` guarda una copia JSON) |
| `db.py` | Base de datos SQLite (`data/nfl.db`): tablas, vistas e historial |
| `base_datos.py` | **Se abre en IDLE** para actualizar y consultar la base con SQL |
| `data.py` | Descarga nflverse y lo guarda en la base |
| `features.py` | Ratings de ataque/defensa ajustados por rival |
| `model.py` | Regresión de margen y total, calibración, ROI |
| `extras.py` | Orquesta props, touchdowns, perfiles y matchups de la semana |
| `lineas_casas.py` | Lee solo las líneas/precios de Kalshi (y DraftKings vía The Odds API con tu llave) y las compara con el modelo |
| `cobertura.py` | Historial «¿cubrió la línea?» por jugador-partido, local/visita, y lectura opcional de `data/lineas_props.csv` |
| `props.py` / `jugadores_data.py` | Modelo de props (HistGradientBoosting + binomial negativa), descarga de jugadores, lesiones y depth charts |
| `matchups.py` / `matchups_data.py` | Presión, blitz, yardas permitidas y rankings ataque vs defensa |
| `reporte_extra.py` | Bloques HTML de matchups, props y calculadora |
| `web.py` | Diseño de la página: pestañas, resumen por partido, selector de partido, texto plegable, frescura |
| `jugadores.py` | LINEA AC (explorador de jugadores, los 32 equipos): Hit Rate semana a semana contra una línea editable |
| `proyecciones.py` | Pestaña PROYECCIONES: cuánto produce cada ofensiva y cuánto permite cada defensa, y el cruce de un partido (método Linemaker) |
| `movimientos.py` | Traspasos y fichajes: quién se movió a dónde, y que el modelo use el equipo vigente de cada jugador |
| `qb.py` | Mariscales: quién abre frente al titular habitual, alertas y medición histórica |
| `backtest.py` | Validación walk-forward 2015-2025 → `outputs/backtest_report.md` |

## Qué dice el backtest (2015-2025)

- Error del margen (RMSE, puntos): mercado 12.72, modelo A 13.10, modelo B 12.74. **Con ratings propios no se supera al mercado**, y con la línea como variable apenas se iguala.
- Probabilidad de ganar (logloss): mercado 0.612, A 0.637, B 0.613. El modelo B queda bien calibrado.
- ROI de apostar con ventaja ≥ umbral: oscila entre negativo y positivo, con errores estándar de 2 a 10 puntos de ROI (mucho mayores en umbrales altos). **No hay evidencia estadística de ventaja rentable.** Los moneylines que sugiere el modelo A pierden dinero, probablemente porque al estar menos seguro que el mercado favorece sistemáticamente a los no favoritos.
- «Calibrado» no significa «con ventaja sobre el mercado».

## Limitaciones conocidas

- **Los modelos de equipos (A y B) no conocen lesiones ni al mariscal titular** (el modelo de props sí excluye a jugadores *Out/Doubtful*). Revisa el reporte oficial de lesiones antes de usar cualquier número.
- El clima usa las condiciones reales del partido en el histórico; al apostar solo hay pronóstico (efecto pequeño, solo en totales).
- Si pides una semana que no es la próxima, los ratings no incluyen los partidos intermedios.
- Faltan cuotas históricas antes de 2006 y en algunos partidos de 2006-2009; el backtest evalúa desde 2015 (si falta una cuota de spread o total se asume −110). Las probabilidades de cubrir/over ignoran el push.
- Probado con pandas 3 y Python 3.13; con versiones más antiguas de pandas no pude probarlo en este entorno.
- Análisis estadístico, no asesoría financiera. Apuesta solo lo que puedas perder y donde sea legal.

## Siguientes pasos

1. Rating de mariscal (EPA/dropback) en el modelo de equipos y ajuste por cambio de titular.
2. Lesiones ponderadas por posición en el modelo de equipos.
3. Props: guardar tus líneas reales de props (`data/lineas_props.csv`) para medir resultados reales; probabilidad de 2+ TD y TD por tierra / por recepción por separado.
4. Guardar las líneas cada día para medir CLV (línea de apertura vs cierre).


## Resumen por equipo (QB, anotadores, WR y RB)

Archivo `por_equipo.py`. En el reporte aparece la sección **«Equipo por equipo»** (enlace «Por equipo» arriba) y se guarda
`outputs/por_equipo_<temporada>_semana<N>.csv`. Para cada equipo que juega: yardas de pase del QB, los 3 jugadores con más
probabilidad de anotar (el primero es el más probable), yardas de recepción de los 3 WR con más targets esperados y yardas por
tierra de los 2 RB con más acarreos esperados, con la probabilidad de OVER y de UNDER.
- Si hay precio de Kalshi: línea = escalón más cercano al 50 % y probabilidad = mezcla modelo + mercado.
- Si no hay: línea «típica» (mediana del jugador sin efecto del rival) y solo modelo; el OVER > 50 % indica que el contexto lo favorece.
- Los equipos en descanso (bye) no tienen proyección y se listan aparte.
- Las líneas son editables: escribe otra línea en la casilla del jugador y la probabilidad de OVER/UNDER se recalcula al instante
  (mezcla con Kalshi si la línea cae dentro de los escalones de Kalshi; si no, solo modelo). El botón ↺ regresa a la original.

## Rankings del matchup: del modelo vs reales

El «ataque #N de 32» de cada matchup sale de los **ratings del modelo** (ajustados por rival; `config.json`: `k` = cuánto cambian
tras cada partido, `shrink` = cuánto se conservan de la temporada anterior). Tienen memoria larga a propósito, así que reaccionan
despacio a un cambio reciente. Debajo de cada franja el reporte muestra el **ranking real**: EPA por jugada esta temporada y en los
últimos 4 partidos, y yardas por partido del ataque. Los datos se actualizan en cada corrida de `semana_nfl.py`.

---

## Elo de los equipos (con quarterback)

Archivo `elo.py`. En el reporte aparece la sección **«Elo de los equipos»** (enlace «Elo» arriba): ranking de los 32 equipos, cuánto ha subido o bajado cada uno (en la temporada, en los últimos 4 partidos y en el último), el aporte del QB que jugó y el Elo de los partidos de la semana junto a la probabilidad del modelo y del mercado.

**Cómo se mueve el Elo.** `cambio = K × margen × (resultado − probabilidad esperada)`. Favorito que pierde baja mucho, favorito que gana sube poco, no favorito que gana sube más. Ganar por más puntos pesa más (con rendimientos decrecientes). Cada partido suma el Elo del **equipo** y el del **QB titular**; si cambia el QB, cambia la fuerza esperada ese mismo día. Los QB nuevos y los equipos con pocos partidos se mueven más.

**Desde cuándo.** Se calcula desde la temporada pasada (todos empiezan en 1500). En el backtest, empezar un año antes casi no pierde precisión frente a usar todo el historial desde 1999 (log-loss 0.630 vs 0.627).

**Qué esperar.** El Elo mejora al modelo A (sin mercado) pero no aporta nada nuevo al modelo B, que ya incluye el spread. Es una lectura de quién va bien o mal, no una señal de apuesta, y **no cambia las probabilidades de las apuestas**. Limitaciones: para partidos pendientes el QB anunciado solo está disponible en parte de los juegos (si falta, se usa el último QB que jugó) y no sabe si el titular está lesionado.

Para cambiar el punto de partida, edita `desde` en `elo.calcular(games, cur, desde=...)`.

---

## Página web

Archivo `publicar_web.py` y guía `PASOS_PAGINA_WEB.md`. Al terminar `semana_nfl.py` se crea la carpeta `docs/` con el reporte (`docs/index.html`, la página principal) y una copia con fecha en `docs/archivo/` (la lista está en `docs/archivo.html`). El archivo `workflow_reporte.yml` (se coloca en `.github/workflows/reporte.yml` dentro de GitHub) permite que GitHub corra el modelo solo y publique esa carpeta como página web visible desde el celular. Los pasos para activarlo están en `PASOS_PAGINA_WEB.md`.

---

## Over / under de puntos (total y por equipo)

Archivo `puntos.py`. En el reporte aparece la sección **«Over / under de puntos»** (enlace «Puntos» arriba), para los partidos pendientes de la semana en curso y la siguiente. Por cada partido hay tres bloques: **total del partido**, **puntos del local** y **puntos de la visita**. En cada uno:

- cuántos puntos espera el modelo y un rango probable (80 %);
- una casilla **«Línea»** donde escribes cualquier número (o usas −1 / +1, o ↺ para volver a la original) y se recalcula al instante la probabilidad de **over**, **under** y **push** (si la línea es un número entero), con la «cuota justa» y el punto de equilibrio de −110 (52.4 %);
- un gráfico con el reparto de marcadores posibles; la parte naranja es el over.

**De dónde salen los números.** El modelo de totales (tB) y el de margen (mB) dan el total y la diferencia esperados; local = (total + margen) / 2 y visita = (total − margen) / 2. Si un partido aún no tiene línea del mercado se usan los modelos A (sin mercado) y el reporte lo avisa. Las líneas iniciales de cada equipo son las implícitas del mercado: (total ± spread) / 2. La incertidumbre sale de los errores reales que tuvo el modelo fuera de muestra desde 2008 (400 percentiles por tipo de error), con los puntos tratados como números enteros.

**Qué tan confiable es.** Probado con el modelo ajustado solo con temporadas previas (2013-2026) y con líneas desplazadas de −14 a +14 puntos del esperado: las probabilidades coincidieron con la frecuencia real con un error típico de 1-2 puntos porcentuales (total y por equipo). **Contra la línea del mercado el modelo no tiene ventaja**: ahí sus probabilidades rondan 50 %, igual que una moneda (log-loss 0.693). Sirve para estimar líneas que el mercado no publica (otro total, el total de un equipo). Limitación: el historial no trae líneas de total por equipo del mercado, así que ese caso se validó con las líneas implícitas.

---

## Marcador: ¿el modelo gana de verdad?

Archivo `marcador.py`. En el reporte aparece la sección **«Marcador»** (enlace arriba, antes de «Historial»). Califica las predicciones que el modelo guardó en la base de datos (`predicciones_modelo` y `lineas_historial`) contra lo que realmente pasó:

- Solo cuenta la **última predicción hecha antes del kickoff** de cada partido (se compara la hora de la predicción con la hora del partido), así nunca se califica algo hecho con el resultado a la vista.
- Cubre **toda la temporada en curso**. Las semanas anteriores a que el modelo empezara a guardar sus predicciones se **reconstruyen** con las predicciones fuera de muestra (modelo entrenado con temporadas previas, ratings con lo ocurrido antes de cada juego) y se comparan con la línea de cierre; en la página se distinguen de las guardadas en vivo (no tienen CLV). Hay una tabla semana por semana.
- Para **ganador, spread y total**: acierto del lado que favorece el modelo (con intervalo del 95 %), unidades ganadas o perdidas con 1 unidad por apuesta y la cuota real (a todos los partidos y solo a los «posibles valores»), log-loss frente al mercado, calibración, error medio en puntos (modelo A, modelo B y la línea del mercado) y **CLV** (si la línea de cierre se movió hacia el lado que eligió el modelo).
- Gráfica de unidades acumuladas, lista de los últimos partidos calificados y una **referencia del historial fuera de muestra (2013-2026)** para comparar.
- Una línea «Para no engañarnos» con lo que habría pasado apostando siempre al mismo lado (local, visita u over).

**La carpeta `semilla/`** trae las predicciones y líneas guardadas en la laptop antes de pasar el modelo a la nube (`predicciones_modelo.csv`, `lineas_historial.csv`); `marcador.py` las suma a lo guardado (sin duplicar) para que la página arranque con esos partidos. Si no quieres usarlas, bórrala.

**Cómo leerlo.** Con pocos partidos todo es ruido: para confirmar una ventaja de 2-3 puntos sobre el punto de equilibrio (52.4 % con cuota −110) hacen falta más de 1,000 apuestas. El CLV es la señal más rápida. Todavía no califica las proyecciones de jugadores (props).

---

## Clima de cada partido

Archivo `clima.py`. En la sección de puntos, debajo del nombre de cada partido, aparece el **pronóstico del estadio para la hora del juego**: temperatura (°C y °F), viento y ráfagas (mph), probabilidad de lluvia o nieve y tipo de clima, con alertas en naranja para viento fuerte (≥ 15 mph), frío (≤ 32 °F) y lluvia probable (≥ 50 %). Con techo cerrado se indica que el clima no afecta; si el techo es retráctil se usa cuántas veces ese estadio se jugó cerrado.

**De dónde sale.** Open-Meteo (gratis, sin llave): se baja el pronóstico por hora de cada estadio (coordenadas de los 32 equipos y de las sedes internacionales) y se resume la ventana del juego (kickoff + 3 horas). Se actualiza en cada corrida, así que es más confiable mientras más cerca esté el partido; a más de ~5 días solo es una idea (la página lo avisa). Cada pronóstico se guarda en la tabla `clima_pronostico` para medir después qué tan bien acertó. Sin internet se usa la última foto guardada (con aviso) y, si no hay, el modelo sigue como antes.

**Qué hace con el modelo.** El modelo de totales ya usaba viento y techo, pero en los partidos pendientes el viento llegaba vacío (= 0). Ahora recibe el pronóstico (topado en 20 mph) y la tarjeta muestra cuánto mueve el total esperado. Para desactivarlo: `"clima_en_modelo": false` en `config.json`; para no bajar el clima: variable de entorno `NFL_SIN_CLIMA=1`.

**Qué esperar (backtest 2013-2026 con el clima REAL de cada juego, mejor que cualquier pronóstico).** Agregar temperatura y viento **no mejora la precisión** del modelo de totales frente a la línea del mercado: el mercado ya los descuenta. Con viento ≥ 15 mph el total real quedó en promedio 1.5 pts bajo la línea (417 partidos, ~2 errores estándar) y apostar el under en esos juegos (sesgo estimado solo con años previos) dio 55 % de acierto y +7.5 % de ROI en 267 apuestas, que con el azar de ±16 unidades no confirma una ventaja. En estadios con techo los totales salieron ~1.3 pts sobre la línea, pero apostar el over ahí no dio ventaja (51 %). Es información útil para entender un partido, no una señal de apuesta probada.

---

## Mariscales (QB titular o suplente)

Archivo `qb.py`. Sección **«Mariscales: ¿juega el titular?»** (enlace arriba) y aviso naranja dentro de la tarjeta de cada partido afectado y en el bloque de Over / under. Para cada partido con props compara el mariscal que usan los props (Kalshi > Ourlads > depth chart, sin los lesionados Out/Doubtful, incluyendo los de ESPN) con el **titular habitual** del equipo (quien abrió más de los últimos 8 partidos) y avisa si: abre un QB distinto (con el motivo: titular de baja/dudoso o sin lesión reportada), el titular está *Questionable*/*Doubtful*, o el titular regresa. «Peso según Elo» estima cuántos puntos de spread vale el cambio con el Elo del QB (25 puntos de Elo ≈ 1 punto); un QB sin historial cuenta como promedio, así que es una referencia optimista.

**Medición (2006-2025, ~10,800 equipos-partido, 22 % con QB distinto).** El mercado ya descuenta el cambio: el equipo cubre el spread el 49 % de las veces con un QB distinto y con el titular de siempre, la diferencia contra la línea es −0.2 ± 0.3 pts, y la dispersión del resultado casi no cambia (13.1 vs 13.2 pts). En QB con menos de 2 abridos previos con ese equipo (912 casos) el descuento fue algo mayor (−0.5 ± 0.4), dentro del ruido. En el total los partidos con cambio quedaron ~0.9 pts abajo de lo normal contra la línea (±0.4, dato débil). **Por eso no se corrigen las probabilidades**: el modelo B parte de la línea, que ya sabe quién juega. El aviso sirve para enterarte y para saber que los props de ese QB tienen más incertidumbre (usan el promedio de debutantes de su ronda del draft, ver «Jugadores sin historial»). La medición se recalcula en cada reporte (`qb.medir`). Solo cubre los partidos de la semana con proyección de props.

---

## Movimientos de jugadores (traspasos y fichajes)

Archivo `movimientos.py`. Las estadísticas por jugador traen el equipo de su **último partido**; si lo traspasaron y aún no juega con el nuevo equipo (p. ej. Jacoby Brissett, ARI → BAL el 6-nov-2026, con semana de descanso de por medio), el modelo lo seguía proyectando con el equipo viejo y el equipo nuevo seguía viendo a otro como mariscal. Ahora, en cada corrida:

- `equipos_vigentes` lee el **depth chart actual** (nflverse, se actualiza a diario) y da el equipo vigente de cada jugador cuyo depth chart no coincide con su último partido. Ese equipo se usa en los props (`props.candidatos`), en los touchdowns, en las lesiones de Ourlads y para decidir quién abre de mariscal (`extras._qb_titular`). Se ve en el log: «Traspasos aún sin partido con su nuevo equipo: N».
- `detectar` lista a los jugadores de ataque (QB, RB, WR, TE) que cambiaron de equipo esta temporada, desde qué semana juegan con el nuevo equipo (o «todavía no juega»), su rol actual y su uso antes/después. Se guarda una foto diaria en la tabla `movimientos_jugadores` de la base de datos.
- `TRASPASOS_2026` es la lista fija de los traspasos del periodo (cierre: martes 10-nov-2026, 4 p. m. ET; fuentes ESPN, DAZN y SI) y se cruza con los datos para avisar si el modelo ya tiene a cada jugador con su equipo nuevo. Los de línea ofensiva/defensiva se muestran pero no entran al modelo de jugadores. **Para el próximo periodo de traspasos hay que actualizar esa lista a mano** (lo detectado con los datos sí es automático).
- En la página: sección **«Movimientos de jugadores»** en la pestaña «Esta semana», insignia «🔁 fichajes» en los partidos afectados, y los avisos de Mariscales ahora dicen «traspasado a …» o «llegó por traspaso desde …».

## LINEA AC (explorador de jugadores, los 32 equipos)

Archivo `jugadores.py` (solo arma datos y HTML; **no cambia ningún cálculo del modelo**). Es la versión estática del dashboard «NFL Props Tracker» (Streamlit) integrada a la página: pestaña **«Equipos y jugadores» → «LINEA AC»** (es la primera sección de esa pestaña).

- Elige temporada, equipo, posición (QB, RB, WR, TE), jugador (titular, banca o lesionado, con su estado) y estadística; filtra por **Local / Visitante / Ambos** y por **Over / Under**.
- Muestra **Hit Rate** y récord (cubrió / no cubrió), promedio real vs línea, Local vs Visitante, gráfica de barras semana a semana con la línea encima, fichas «¿Cubrió la línea?», detalle semana a semana, bloque «Acarreos por partido» para los RB y los **puntos totales del partido** del equipo (Over/Under, local/visitante).
- **Línea editable**: parte de la línea «normal» del modelo (o del promedio de la temporada si el jugador no tiene proyección); botones para usar la del modelo, el promedio o la de Kalshi. Si el jugador tiene proyección, la tarjeta «Próximo partido» da su valor esperado, rango típico y el % de superar *tu* línea.
- Reglas idénticas al dashboard: Over cubre si real > línea; Under si real < línea; push (igual) no cuenta; «No jugó» y «Sin línea» no cuentan; **Hit Rate = cubrió ÷ (cubrió + no cubrió)**; Local/Visitante sale del calendario.
- Estadísticas: yardas de pase, TDs de pase, yardas por tierra, acarreos, recepciones, yardas por recepción, TD (por tierra o recepción), y además pases completos, intercepciones objetivos (targets), intentos de pase, TD por tierra, TD por recepción y yardas por tierra + recepción. El selector de estadística muestra solo las que aplican a la posición elegida. Temporada actual y la anterior, solo temporada regular.
- Los datos van embebidos en la página (sin servidor y sin descargas nuevas: salen de la misma base de datos). El jugador traspasado aparece con su equipo vigente (ver «Movimientos»). Se probó contra la lógica original del dashboard (`metrics.py`) en 400 combinaciones al azar: 0 diferencias.
- No se usa The Odds API: las líneas «reales» de casas por semana no existen gratis en forma histórica; el Hit Rate se mide contra la línea que escribas o la normal del modelo (ver «Líneas automáticas de Kalshi» para las actuales).

## Combinadas del mismo partido

En `puntos.py`, al final de cada tarjeta de Over / under: **«Combinadas del mismo partido»**. Con tu **spread** (−3.5 = el local es favorito por 3.5) y tu **total** (ambos editables, ↺ para volver a las líneas del mercado) da la probabilidad conjunta de 8 combinaciones: *cada equipo cubre el spread* y *cada equipo gana*, cada una con *OVER* o *UNDER*, con la **cuota justa**, la probabilidad que saldría si las dos cosas fueran independientes, y una casilla opcional **«Cuota de la casa»** (ej. +250) que muestra la ventaja (modelo − probabilidad implícita).

**Cómo se calcula.** Se parte del margen y total esperados del partido y se les suman 1,500 pares de errores reales del mismo juego (margen y total, fuera de muestra, modelo A o B según el partido); los puntos se redondean a enteros y los empates con la línea (push) se excluyen. **Hallazgo del historial (5,046 partidos):** la correlación entre el error del margen y el error del total es ≈ 0.02, así que la probabilidad conjunta sale prácticamente igual al producto de las dos por separado, y modelarla no mejora la precisión (Brier 0.1842 vs 0.1839 del producto; la combinada «cubre + over» real fue 24.3 %). Es decir: no hay una «correlación mágica» que explotar; la utilidad es calcular cualquier combinación con tus líneas y comparar contra el precio de la casa (que incluye su margen). Como todo lo de puntos, contra la línea del mercado el modelo no tiene ventaja confirmada.

---

## Actualización más frecuente

El workflow de GitHub (`.github/workflows/reporte.yml`) corre **cada 3 horas domingo, lunes y jueves** (días de partido: las lesiones, el clima y los mariscales cambian hasta el kickoff) y **una vez al día martes, miércoles, viernes y sábado**. También a mano: Actions > «Reporte NFL» > Run workflow. Los horarios (cron) están en UTC.

---

## Diseño de la página (pestañas y un partido a la vez)

Archivo `web.py` (solo acomoda; **no calcula nada**). El reporte ahora tiene 4 pestañas fijas arriba:

- **Esta semana**: el resumen de valor, **una fila por partido** (modelo vs mercado, línea, marcador esperado y avisos: ✔ posible valor, 🏈 mariscal distinto/en duda, 💨 viento, 🥶 frío, 💧 lluvia/nieve, 🩹 jugadores con proyección fuera o dudosos), la tabla de mariscales y las gráficas (plegadas).
- **Partidos**: un selector con todos los partidos (semana en curso y siguiente) y, del partido elegido, cuatro sub-pestañas: **Apuestas** (modelo vs mercado y Kalshi), **Puntos y combinadas** (tus líneas del total, de cada equipo y las combinadas), **Props y TD** y **Matchup**. «Mostrar todos» los despliega uno tras otro. Tocar «Ver partido →» en cualquier fila te lleva directo.
- **Equipos y jugadores**: equipo por equipo, Elo, touchdowns, Kalshi y props destacados.
- **Calidad**: marcador, qué tanto confiar, historial y glosario («Cómo leer»).

Además: los párrafos explicativos largos quedan en un «Cómo se lee» plegable; en celular las tablas anchas se deslizan con la primera columna fija, los botones son más grandes y las casillas no hacen zoom; botón ↑ para volver arriba; y junto al título un indicador **«actualizado hace X · próximo partido: …»** que se recalcula en el navegador (se pone naranja si faltan menos de 24 h para un partido y los datos tienen más de 6 h). Los enlaces antiguos (`#td`, `#marcador`, `#puntos`…) siguen funcionando y abren la pestaña correcta. Las horas se muestran en hora de Ciudad de México.

**Nada de lo que hacías se perdió.** Las calculadoras (líneas editables del total y de cada equipo, combinadas, props, touchdowns, equipo por equipo y la combinada de jugadores) son las mismas y escuchan eventos a nivel de documento, así que funcionan igual aunque estén en otra pestaña. Se probó automáticamente en un navegador contra el diseño anterior con una semana completa: 243 cálculos de puntos, 108 de combinadas, 804 props, 326 touchdowns, 157 de equipo por equipo y la combinada de jugadores dieron **resultados idénticos**. Si algo falla al armar el diseño nuevo, `reporte.py` usa el anterior (una sola página larga); para forzarlo: variable de entorno `NFL_DISENO_ANTERIOR=1`.

Peso: una semana completa pesa ~2.5 MB de HTML (≈0.6 MB comprimido por GitHub Pages; casi todo son las tablas de props); las imágenes cargan en diferido.

## PROYECCIONES (cuánto produce una ofensiva y cuánto permite una defensa)

Archivo `proyecciones.py` (solo lee datos; **no cambia ningún cálculo del modelo**, sin líneas ni momios). Pestaña propia **«PROYECCIONES»**, también en el menú «☰ Todo». Parte del método de `proyeccion_linemaker.py` (volumen × lo que permite la defensa).

- **Ofensivas**: tabla de los 32 equipos con lo que *produce* cada una por partido (puntos, jugadas, puntos por jugada, yardas totales, de pase, completos, intentos, yardas por completo, yardas por tierra, acarreos, yardas por acarreo, TD de pase y por tierra). Se ordena tocando el nombre de la columna; verde = 8 mejores, rojo = 8 peores; fila final = promedio de la liga.
- **Defensas**: la misma tabla con lo que *permite* cada defensa (lo que produjeron sus rivales); menos es mejor.
- **Cruce ofensiva vs defensa**: eliges un equipo y su rival (se rellena con el próximo partido; botón ⇄ para cambiar) y ves, para las dos ofensivas, lo que produce, lo que permite la defensa y la **proyección** con las fórmulas del pizarrón: pase = completos por partido × yardas por completo permitidas; tierra = acarreos por partido × yardas por acarreo permitidas; puntos = promedio de (jugadas × pts/jugada propios) y (jugadas × pts/jugada que permite el rival). Debajo, los QB, RB y WR/TE del equipo con su volumen, su promedio y su proyección de yardas contra esa defensa (WR/TE = completos del equipo × yardas por completo permitidas × target share).
- Datos de la temporada en curso (solo temporada regular), de `player_weeks`, los juegos terminados y los snaps ofensivos (jugadas). Se revisó contra un cálculo independiente (BAL: 204.7 yardas de pase y 137.8 por tierra por partido, iguales). Las fórmulas coinciden con el archivo original (500 casos, diferencia máxima 7e-8).
- Limitaciones: promedios de temporada (no ajustan por lesiones, clima ni ritmo); no hay marcador por mitades, así que no hay «1er tiempo»; las yardas por acarreo incluyen acarreos de QB y receptores; la lista de jugadores incluye solo a quien ya tiene volumen en la temporada.
