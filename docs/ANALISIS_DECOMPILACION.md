# Zone 66 - Análisis de decompilación y propuesta de aumento de FPS

Fecha del análisis: 2008-02-25
Herramientas usadas: `objdump`, `ndisasm` (NASM), HIEW, Python 2 (script propio, ver §9), inspección manual de cabeceras MZ y de recursos.
Herramientas que **no** estaban disponibles en este entorno y que se recomiendan para la siguiente fase: IDA Pro, radare, DOSBox (compilado con `debug=heavy`, para tener el depurador integrado).

---

## 1. Resumen ejecutivo

- El "ejecutable del juego" real es **`GAME.EXE`** (62 220 bytes). `ZONE66.EXE` (1 204 bytes) es solo un *launcher* que encadena `INTRO.EXE` → `GAME.EXE`.
- `GAME.EXE` e `INTRO.EXE` **no son binarios DOS convencionales de 16 bits**: son programas de **modo protegido de 32 bits** que arrancan mediante un **DOS extender propio, escrito enteramente a mano en ensamblador**, sin usar ninguna librería de terceros (no hay PMODE, DOS4GW, Watcom, CauseWay, etc.).
- El motor no proviene de código C compilado: **no existe ni un solo prólogo de función estilo compilador** (`push ebp; mov ebp,esp`) en los 62 KB del binario. Es ensamblador x86 optimizado a mano de principio a fin.
- El renderizado es **VGA por puertos de I/O directos** (no usa `int 10h` de la BIOS en absoluto), consistente con un modo tipo "Mode X" (256 colores, planar, sin encadenar).
- Los assets `.Z66` no son un archivo/contenedor genérico: son recursos individuales, la mayoría con una **cabecera propia de 4 bytes = tamaño descomprimido**, lo que indica un **compresor propietario único compartido por todo el juego** (probablemente LZ/RLE a medida).
- **El objetivo concreto de este documento** es evaluar cómo subir el límite de 30 fps del juego. La conclusión preliminar (§6) es que el límite está atado a la temporización de vídeo (PIT y/o retrace VGA), pero **no se ha podido fijar de forma estática qué mecanismo exacto lo controla**; hace falta trazado dinámico con depurador para confirmarlo antes de tocar nada. Ver §10 para las opciones concretas y la recomendación.

---

## 2. Inventario de binarios y su relación

<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Archivo</th><th>Tamaño</th><th>Rol</th></tr>
<tr><td><code>ZONE66.EXE</code></td><td>1 204 B</td><td>Launcher/stub DOS real-mode. Contiene las cadenas <code>INTRO.EXE</code>, <code>GAME.EXE</code>, <code>&nbsp;Tran is Evil!!!</code>. Solo ejecuta <code>INTRO.EXE</code> y luego <code>GAME.EXE</code>.</td></tr>
<tr><td><code>INTRO.EXE</code></td><td>43 004 B</td><td>Pantalla de introducción/título. Usa <strong>el mismo bootstrap de extender</strong> que <code>GAME.EXE</code> (código de arranque binario-idéntico, ver &sect;3).</td></tr>
<tr><td><code>GAME.EXE</code></td><td>62 220 B</td><td><strong>El motor del juego</strong>: render, input, sonido, lógica, menús. Es el único binario relevante para el objetivo de subir los fps.</td></tr>
<tr><td><code>HELPME.EXE</code></td><td>5 552 B</td><td>Utilidad de ayuda/diagnóstico aparte, DOS real-mode normal (cabecera MZ distinta, sin el extender). Sin interés para este análisis.</td></tr>
<tr><td><code>*.Z66</code> (193 archivos)</td><td>-</td><td>Recursos de datos: gráficos, música, sfx, mapas, paletas, fuentes, demos, savegame/preferencias. Ver &sect;7&ndash;&sect;8. No afectan al framerate, solo se documentan para tener el inventario completo.</td></tr>
<tr><td><code>*.DOC</code> (4 archivos)</td><td>-</td><td>Documentación textual original (manual, licencia, orden de compra). Sin interés técnico.</td></tr>
</table>

---

## 3. Arranque de `GAME.EXE`: DOS extender propio (real mode → protected mode)

Cabecera MZ de `GAME.EXE`: `CS:IP` inicial = `0000:03D6` → offset de fichero `0x5D6` (512 bytes de cabecera + 0x3D6). Solo **20 entradas de reubicación** - muy pocas para 62 KB, coherente con un único segmento de código/datos casi plano.

El mismo punto de entrada en `INTRO.EXE` (offset 512+0x3DD) es **byte a byte casi idéntico** al de `GAME.EXE`: ambos comparten el mismo módulo de arranque/extender enlazado en cada ejecutable.

Desensamblado del arranque (16 bits, real mode) muestra, en este orden:

1. **Habilitación de A20**: prueba rápida vía puerto `0x92` y, si falla, secuencia clásica por el controlador de teclado (`out 0x64,0xD1` / `out 0x60,0xDF`).
2. **Detección de CPU/386**: bucle de calibración usando el PIT (Programmable Interval Timer) en modo *free-run*: `out 43h,36h` + `out 40h,0 / out 40h,0`, seguido de lecturas repetidas de `in al,40h` para medir ciclos de reloj. (String asociada: `"386 or better not detected!!!"`).
3. **Negociación de modo protegido**, en este orden de preferencia (con mensajes de error correspondientes en el binario):
   - `int 2Fh, AX=1687h` → sondea un **host DPMI** ya cargado (p. ej. HIMEM/EMM386 con DPMI, o un extender de terceros ya residente).
   - Si no hay DPMI: `int 2Fh, AX=4300h` → sondea **VCPI** (interfaz clásica de EMM386/QEMM).
   - Llamadas a `int 67h` con `AH=DEh` (grupo de funciones VCPI estándar: versión, páginas libres, `alloc/free page` - se ven exactamente los códigos `DE04h`/`DE05h` en un bucle de asignación de páginas, y `DE0Ah` justo antes del salto a modo protegido, que es la función VCPI para obtener el *entry point* de conmutación).
   - Mensajes de error para los casos sin salida: *"System is already in V86 mode, and no VCPI or DPMI found!!!"*, *"DPMI host is not 32bit!!!"*, *"Couldn't enable A20 gate!!!"*, *"Extended memory allocation failure"*, etc.
4. **Construcción manual de descriptores** (GDT) vía `int 31h` repetidos: asignación de descriptores (`AX=0000h,CX=3`), asignación de memoria (`AX=0500h`/`0501h` - *get free memory info* / *allocate memory block*), y ajuste de *base/límite* de al menos 3 descriptores planos que terminan cargados en `ES`, `FS`, `GS` (probablemente el "arena" plano que cubre memoria convencional + extendida).
5. **Salto real a 32 bits**: en offset de fichero `0xAB9` se ejecuta

       push dword ptr cs:[0xE8C]   ; offset dentro del segmento 32-bit
       push 0x210                  ; selector de segmento de código (GDT index 0x42)
       retf                        ; far return => CS:EIP = 0210:offset, modo protegido 32-bit

   Este es el instante exacto en el que termina el arranque real-mode y comienza la ejecución del motor de 32 bits.

**Implicación para el objetivo de este documento**: cualquier parche al limitador de fps (§10) tiene que aplicarse **después** de este salto, es decir, dentro del segmento de 32 bits - no hay nada de temporización relevante en la parte real-mode salvo la calibración de CPU del arranque (paso 2), que no vuelve a ejecutarse durante el juego.

---

## 4. Naturaleza del código: ensamblador puro, no C compilado

Búsqueda exhaustiva de firmas de prólogo de función de compilador (`55 8B EC` = `push ebp; mov ebp,esp`, y su variante `55 89 E5`) en los 62 220 bytes de `GAME.EXE`: **0 coincidencias**.

Combinado con el uso de tablas de punteros a función llamadas con `call ptr cs:[...]` / `lcall [...]`, saltos calculados, y manejo de registros muy ajustado (típico de la era: mismo estilo que otros juegos DOS de referencia de 1992-93), la conclusión es que **el motor entero está escrito a mano en ensamblador x86**, no generado por un compilador C/C++. Esto es coherente con el rendimiento exigido por un shooter de scroll con muchos sprites a 30 fps en hardware 386/486 de la época.

**Consecuencia directa para el objetivo de este documento**: no hay una función "FPS_LIMIT" reconocible con nombre de símbolo ni tabla de configuración clara - localizar el limitador implica encontrar, entre cientos de instrucciones `OUT`/`IN` sin comentar, la o las concretas que fijan el ritmo. Es trabajo de ingeniería inversa de comportamiento, no de lectura directa de código fuente.

---

## 5. Subsistema de vídeo

- **Cero usos de `int 10h`** (BIOS de vídeo) en todo el binario. Todo el control de VGA es por puertos de I/O directos.
- 314 instrucciones `OUT DX,AL` y 222 `IN AL,DX` en `GAME.EXE`. La mayoría de estos accesos cargan el número de puerto en `DX` desde una variable/tabla en memoria en vez de una constante inmediata - patrón típico de una rutina genérica que aplica una lista de pares *(puerto, valor)* a los registros del Sequencer/Graphics Controller/CRTC de la VGA, muy en línea con las técnicas de **"Mode X"** popularizadas por Michael Abrash para esa generación de juegos DOS (256 colores, planar, sin encadenar, doble buffer con *page flip*).
- No se encontraron constantes inmediatas de puertos VGA (`03C4h`, `03CEh`, `03D4h`, `03DAh`) cargadas directamente vía `mov dx,imm16` - refuerza que el acceso es indirecto/tabulado y que hace falta trazado dinámico (depurador de DOSBox) o IDA Pro sobre el segmento de 32 bits para extraer la tabla exacta de registros VGA programados.
- **Este subsistema es, junto con el de temporización (§6), el que hay que entender a fondo para tocar los fps**: si el juego usa *page flipping* sincronizado al retrace (muy probable en Mode X), el límite de 30 fps puede estar impuesto aquí y no en el PIT.

---

## 6. Temporización / PIT - el limitador de fps

Se localizaron **6 reprogramaciones del PIT** (más la de calibración de CPU del arranque, §3):

- La reprogramación en offset `0x69CA` usa el byte de comando `0xB6` = canal **2** (no el canal 0 del reloj maestro), modo 3, seguido de escritura a `out 42h` (puerto de datos del canal 2). El canal 2 del PIT está cableado al **altavoz PC (PC speaker)** - esto es generación de tono para audio (coherente con las cadenas `"Sound Blaster on IRQ 3,5, or 7."`, `"Gravis Ultrasound."`), **no** es el limitador de fps. Descartada.
- Las otras cuatro reprogramaciones (`0x694A`, `0x6B6B`, `0x7DB8`, `0x7DF7`) caen en zonas del archivo que ya pertenecen al **segmento de 32 bits** (post-conmutación), donde el desensamblado en modo 16 bits no es válido - hace falta volver a desensamblarlas en modo 32 bits con la base de carga correcta (que DPMI asigna dinámicamente en tiempo de ejecución, no es un offset fijo de fichero). **No se ha podido fijar de forma estática, en esta pasada, si alguna de ellas reprograma el canal 0 (reloj maestro/IRQ0), que sería el candidato directo a fijar el ritmo de 30 fps.**
- **Hipótesis alternativa, igual de plausible**: si ninguna reprogramación toca el canal 0, es muy probable que el bucle principal esté sincronizado por **espera activa al retroceso vertical de la VGA** (polling del bit 3 del puerto `03DAh`) - coherente con no haber encontrado ninguna constante `03DAh` inmediata (se accede seguramente vía tabla, como en §5). Esto encajaría con "corre a ~30 fps" en hardware VGA estándar (retrace a 60 Hz, actualizando cada 2 retrocesos).

**Estas dos hipótesis (canal 0 del PIT vs. espera de retrace VGA) llevan a parches y consecuencias distintas - ver §10.** No se puede recomendar un parche concreto sin resolver primero esta ambigüedad con trazado dinámico:

1. Localizar el manejador de `IRQ0` instalado vía DPMI (`int 31h, AX=0203h`/`0204h`/`0205h`/`0206h` - *set/get protected-mode interrupt vector*), usando DOSBox con el depurador integrado (`debug=heavy`) y un breakpoint en el `retf` de conmutación a modo protegido (fichero offset `0xAB9`).
2. Si hay un manejador de IRQ0 propio, leer el valor exacto de recarga escrito en el canal 0 del PIT para confirmar la frecuencia de tick lógico.
3. Si no lo hay, confirmar la hipótesis de retrace poniendo un breakpoint de lectura sobre el puerto `03DAh`.

---

## 7. Formato de recursos `.Z66`: contenedor con compresión propietaria

Comprobación sistemática: los primeros 4 bytes (little-endian, `uint32`) de la mayoría de los `.Z66` coinciden con un **tamaño descomprimido plausible**, mayor que el tamaño en disco:

<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Archivo</th><th align="right">Tamaño en disco</th><th align="right">4 bytes iniciales (LE)</th><th align="right">Ratio</th></tr>
<tr><td><code>FONT.Z66</code></td><td align="right">1 305</td><td align="right">3 065</td><td align="right">2.35&times;</td></tr>
<tr><td><code>FONT2.Z66</code></td><td align="right">1 999</td><td align="right">4 766</td><td align="right">2.38&times;</td></tr>
<tr><td><code>TITLE.Z66</code></td><td align="right">29 966</td><td align="right"><strong>64 000</strong></td><td align="right">2.14&times;</td></tr>
<tr><td><code>MAINGRFX.Z66</code></td><td align="right">17 687</td><td align="right">30 694</td><td align="right">1.74&times;</td></tr>
<tr><td><code>MAPAGRFX.Z66</code></td><td align="right">163 317</td><td align="right">277 504</td><td align="right">1.70&times;</td></tr>
<tr><td><code>DSFX.Z66</code> (sfx)</td><td align="right">39 227</td><td align="right">39 669</td><td align="right">1.01&times;</td></tr>
<tr><td><code>M01GMUZ.Z66</code> (música)</td><td align="right">47 378</td><td align="right">50 207</td><td align="right">1.06&times;</td></tr>
</table>

`TITLE.Z66` descomprime a **exactamente 64 000 bytes = 320×200×1 byte/píxel** → confirma que es un framebuffer VGA plano de 256 colores tras descomprimir, y valida el modelo de "tamaño descomprimido en cabecera + stream comprimido". Los archivos de audio (sfx/música) comprimen casi nada (ratio ≈1.0), como es esperable en PCM. `HIGHS.Z66` (marcador) y `PREFS.Z66` (config) **no** siguen el patrón - son datos crudos sin comprimir, como corresponde a archivos de guardado pequeños.

El stream comprimido inspeccionado (`FONT.Z66`) no muestra RLE trivial a simple vista; es compatible con un **LZ propietario ligero tipo LZSS** (bytes de máscara de bits + literales/coincidencias), muy común en juegos DOS de esa época.

Este apartado no incide directamente en el objetivo de fps, pero se documenta porque cualquier parche sobre `GAME.EXE` que toque rutinas cercanas al cargador de recursos debe evitar confundir el códec de descompresión con el bucle de temporización (comparten la zona post-`0xAB9` del segmento de 32 bits).

---

## 8. Taxonomía de assets (193 archivos `.Z66`)

<table border="1" cellpadding="4" cellspacing="0">
<tr><th>Prefijo/sufijo</th><th>Cantidad aprox.</th><th>Contenido probable</th></tr>
<tr><td><code>MAP{A-H}.Z66</code>, <code>MAP{A-H}DAT.Z66</code>, <code>MAP{A-H}DAT{2-6}.Z66</code>, <code>MAP{A-H}GRFX.Z66</code>, <code>MAP{A-H}PIC.Z66</code>, <code>MAP{A-H}M0.Z66</code></td><td>8 mapas &times; ~9 archivos</td><td>Definición de niveles/misiones (A&ndash;H), sus gráficos de terreno/tiles y minimapa.</td></tr>
<tr><td><code>CN?{0-5}GRFX.Z66</code>, <code>CNG.Z66</code></td><td>~35</td><td>Gráficos de "enemigos"/personajes de radio o menús contextuales (naves enemigas, por prefijo A&ndash;H).</td></tr>
<tr><td><code>SH?{0-2,A}GRFX.Z66</code></td><td>~30</td><td>Gráficos de naves del jugador (Ship), por variante A&ndash;H.</td></tr>
<tr><td><code>M??GMUZ.Z66</code> (p. ej. <code>M01GMUZ</code>, <code>MA2GMUZ</code>, <code>ME3GMUZ</code>&hellip;)</td><td>~24</td><td>Música/tracker por nivel y sección.</td></tr>
<tr><td><code>FONT.Z66</code>, <code>FONT2.Z66</code></td><td>2</td><td>Tipografías bitmap.</td></tr>
<tr><td><code>MAINGRFX.Z66</code>, <code>MISCGRFX.Z66</code>, <code>TITLE.Z66</code></td><td>3</td><td>UI principal, elementos varios, pantalla de título.</td></tr>
<tr><td><code>DSFX.Z66</code>, <code>SBG.Z66</code></td><td>2</td><td>Efectos de sonido digitales.</td></tr>
<tr><td><code>MPAL.Z66</code>, <code>TPAL.Z66</code></td><td>2</td><td>Paletas (menú/título).</td></tr>
<tr><td><code>ZIL0-2.Z66</code>, <code>ZIM00-02.Z66</code>, <code>ZIM2.Z66</code></td><td>7</td><td>Probablemente animaciones/cinemáticas o secuencias de introducción.</td></tr>
<tr><td><code>DEMOK.Z66</code>, <code>DEMOT.Z66</code>, <code>ZDEMO0.Z66</code></td><td>3</td><td>Demos grabadas (probablemente <em>input replays</em>, no vídeo).</td></tr>
<tr><td><code>HIGHS.Z66</code>, <code>PREFS.Z66</code></td><td>2</td><td>Puntuaciones altas y preferencias (sin comprimir, formato propio pequeño).</td></tr>
<tr><td><code>OS.Z66</code></td><td>1</td><td>582 KB - <strong>no es código ni "sistema operativo"</strong>: inspección directa muestra patrones de bloque repetidos de 32 bytes (mosaico de terreno) y entropía baja (5.47 bits/byte) &rarr; es un asset gráfico grande (terreno/fondo), no ejecutable.</td></tr>
<tr><td><code>ET.Z66</code>, <code>INSTR.Z66</code>, <code>ZONE66T.Z66</code></td><td>3</td><td>Texto de instrucciones/créditos en pantalla, probablemente comprimido igual que el resto.</td></tr>
</table>

---

## 9. Herramientas usadas y recomendadas

**Disponibles y usadas en este análisis** (entorno sin conexión a repos ni IDA/radare/DOSBox preinstalados):
- `objdump`, `ndisasm` (del paquete NASM), `strings`, `xxd` (sistema).
- HIEW (Hacker's View) para inspección hexadecimal y desensamblado rápido embebido de fragmentos puntuales.
- Python 2 con un script propio (`analizar_z66.py`, incluido junto a este documento) de parseo de cabecera MZ y estadísticas de entropía (sin bibliotecas de desensamblado de terceros - no había nada equivalente disponible), ejecutado en un entorno virtual creado con `virtualenv` para esta sesión de análisis.

**Recomendadas para la siguiente fase** (no disponibles aquí):
- **IDA Pro**: para desensamblar y anotar el segmento de 32 bits completo con soporte de x86 y cross-references; requiere fijar manualmente la base de carga (el juego se relocaliza en memoria extendida vía DPMI, no en un offset fijo de archivo).
- **radare**: alternativa ligera a IDA Pro, buena para scripting del análisis de las llamadas a `int 31h` (mapear cada una a su función DPMI exacta) y de las tablas de punteros de función.
- **DOSBox compilado con el depurador integrado** (build `debug=heavy`): imprescindible para trazado dinámico - poner breakpoints en el `retf` de cambio a modo protegido (offset `0xAB9`), en las reprogramaciones del PIT, y en el puerto `03DAh`, para resolver la ambigüedad del §6.

---

## 10. Propuesta para aumentar los fps

Partiendo de las dos hipótesis del §6 sobre qué controla el límite de 30 fps, se plantean tres vías, de menor a mayor esfuerzo:

**Opción A - Parche binario directo sobre `GAME.EXE` (recomendada como primer paso).**
Una vez identificado con el depurador si el limitador es la recarga del canal 0 del PIT o el polling del retrace VGA (§6), el parche en sí es de una o pocas instrucciones: cambiar el valor de recarga del PIT (si aplica) o eliminar/relajar la espera activa sobre el bit 3 de `03DAh`. Es el camino de menor esfuerzo porque no toca el resto del motor. **El riesgo real no es técnico sino de diseño**: en un motor de esta era, sin arquitectura *fixed-timestep*, es habitual que la física (velocidad de naves, proyectiles, *scroll*) esté atada al mismo contador que dibuja el frame. Si es así, subir el límite de fps también aceleraría el juego entero - habría que comprobarlo jugando una partida tras el parche, y si ocurre, el "parche de una instrucción" deja de ser tan trivial (pasaría a requerir localizar y desacoplar las rutinas de movimiento del contador de vídeo, que ya es ingeniería inversa completa de la física, ver Opción C).

**Opción B - Forzar más ciclos de CPU en el emulador (DOSBox), sin tocar el binario.**
DOSBox permite subir el número de "cycles" emulados por segundo desde su configuración, lo que en muchos juegos DOS antiguos que limitan el ritmo por *busy-wait* de CPU (sin sincronizar a temporizador real) produce más fps de forma directa. **Esta vía probablemente no sirva aquí**: si la hipótesis de retrace VGA del §6 es la correcta, el límite no depende de la velocidad de CPU emulada, sino del ritmo de refresco de vídeo que el propio DOSBox también emula a una frecuencia fija (normalmente 70 Hz para modos VGA) - subir "cycles" no cambiaría nada. Solo tendría efecto si el limitador resultase ser un bucle de espera por CPU sin relación con el hardware de vídeo, hipótesis que el análisis estático no respalda. Se incluye por completitud, pero no se recomienda como vía principal sin antes descartar la hipótesis de retrace.

**Opción C - Reimplementación del motor sobre una capa portátil (proyecto de fondo, no un parche).**
Si la Opción A resulta inviable porque la física está acoplada al framerate, la única vía robusta para subir los fps **sin alterar la velocidad ni el balance del juego** es reimplementar el bucle principal separando el *update* lógico (a la cadencia original, ~30 Hz, para no tocar física/colisiones) del *render* (a la tasa que se quiera, 60 fps o *uncapped*). Esto exige entender el motor a fondo con IDA Pro + trazado dinámico (mucho más esfuerzo que un parche), y reescribir el renderer Mode X como un framebuffer indexado de 320×200 subido como textura de OpenGL (paleta de 256 colores expandida a RGB), usando SDL 1.2 para ventana/input. Los assets originales se reutilizarían tal cual una vez extraído el códec de compresión (§7), sin recrearlos a mano.

**Recomendación**: empezar por la Opción A como parche exploratorio de bajo coste - además de (posiblemente) subir los fps, confirma empíricamente cuál de las dos hipótesis del §6 es la correcta, información necesaria de todos modos. Si el parche altera la velocidad de juego de forma inaceptable, pasar directamente a la Opción C; no se recomienda invertir tiempo en la Opción B salvo que el trazado dinámico descarte la hipótesis de retrace.

---

## 11. Hoja de ruta propuesta

1. **Resolver la ambigüedad del §6** con DOSBox (`debug=heavy`) + breakpoints en `0xAB9`, las reprogramaciones del PIT y el puerto `03DAh`: confirmar si el límite de 30 fps es el canal 0 del PIT o el retrace VGA.
2. **Aplicar el parche exploratorio (Opción A, §10)** sobre una copia de `GAME.EXE` y jugar una partida completa para comprobar si la velocidad del juego cambia junto con el framerate.
3. Si la física no se ve afectada: **documentar el parche y darlo por bueno** - es la solución más simple y de menor riesgo.
4. Si la física sí se acelera: **descartar el parche simple** y pasar a la Opción C - localizar con IDA Pro las rutinas de movimiento/colisiones y evaluar el desacople update/render.
5. En paralelo, y con independencia de qué opción se siga: **extraer el códec de compresión de `.Z66`** (§7) - es la tarea de mayor apalancamiento del proyecto completo, porque desbloquea inspección visual de todos los assets sin depender del emulador.
6. Si se llega a la Opción C, seguir con **reimplementación del renderer** (Mode X → textura OpenGL) y del **bucle principal** (update fijo / render desacoplado) como fases separadas, verificando cada una contra el original en DOSBox.

---

## 12. Notas y avisos

- Este análisis es puramente técnico/preservacionista sobre un juego comercial de 1993 (Zone 66, Renaissance/21st Century Entertainment). Cualquier redistribución de los assets originales debe respetar los términos de `LICENSE.DOC` incluidos en el propio juego.
- Nada de lo anterior ha sido verificado ejecutando el juego (no hay DOSBox en este entorno); todas las conclusiones vienen de análisis estático de los binarios y archivos de datos tal como están en `game/`.

---

## 13. Anexo: `analizar_z66.py` y cómo funciona

El script mencionado en el §9 (`analizar_z66.py`, en este mismo directorio) es el que se usó para obtener las cifras exactas de los §3, §7 y §8 (offset de entrada de `GAME.EXE`, ratios de compresión de los `.Z66` y la entropía de `OS.Z66`).

**Cómo funciona:**

- `parse_mz_header(path)` - lee los 28 primeros bytes del fichero (el tamaño fijo de una cabecera MZ clásica) y los desempaqueta con `struct.unpack("<2s13H", ...)`: 2 bytes de firma (`"MZ"`) seguidos de 13 palabras de 16 bits sin signo, en little-endian (`<`). De ahí saca `e_cparhdr` (tamaño de la cabecera en párrafos de 16 bytes) y `e_ip`/`e_cs` (offset y segmento del punto de entrada relativo al inicio del segmento de código). El offset de fichero real del punto de entrada es `e_cparhdr*16 + e_ip` - así es como se obtuvo el `0x5D6` de `GAME.EXE` en el §3. También expone `e_crlc`, el número de entradas de la tabla de reubicación.
- `shannon_entropy(data)` - cuenta cuántas veces aparece cada uno de los 256 valores de byte posibles en el fichero, y con esas frecuencias calcula la entropía de Shannon en bits/byte: `-Σ p(b)·log2(p(b))` para cada valor de byte `b` con probabilidad `p(b)`. Un fichero con entropía cercana a 8 bits/byte es indistinguible de ruido aleatorio (compatible con datos comprimidos); una entropía baja indica patrones repetidos (como el mosaico de terreno de `OS.Z66`, que dio 5.47).
- `z66_declared_size(data)` - interpreta los primeros 4 bytes del fichero como un entero sin signo de 32 bits little-endian (`struct.unpack("<I", ...)`), que es el campo que los `.Z66` usan para declarar el tamaño descomprimido (§7).
- `analizar_exe(path)` / `analizar_z66(path)` - imprimen un informe legible combinando las funciones anteriores: para un `.EXE`, la cabecera y el punto de entrada; para un `.Z66`, el tamaño en disco, el tamaño declarado, el ratio entre ambos y la entropía, con una nota heurística según el valor (ratio ~1.0 → probablemente sin comprimir; entropía >7.5 → compatible con stream comprimido; entropía <6.0 → datos con patrones).
- `analizar(path)` - decide cuál de las dos rutinas usar mirando la extensión del fichero (`.EXE` o `.Z66`).
- `main()` - punto de entrada de línea de comandos: recorre `sys.argv[1:]` (uno o varios ficheros) y llama a `analizar()` sobre cada uno, capturando errores de fichero no encontrado o cabecera inválida sin abortar el resto del lote.

No usa ninguna biblioteca de desensamblado (no había nada equivalente disponible en 2008, ver §9) - solo lee bytes crudos con `struct`, por lo que todo lo relativo a instrucciones x86 (§3-§6) se hizo a mano con `objdump`/`ndisasm`/HIEW, no con este script.

---
Jonathan Toledo.
