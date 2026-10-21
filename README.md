# Price Tracker

Tracker personal que intenta leer precios publicados en páginas de productos, guarda un histórico CSV y envía un resumen diario por Gmail mediante GitHub Actions.

## Archivos
- `tracker.py`: lectura de precios, histórico y correo.
- `products.json`: lista de productos y URLs a vigilar.
- `prices.csv`: histórico diario.
- `.github/workflows/price_tracker.yml`: ejecución automática diaria a las 12:00 UTC y ejecución manual.

## Configuración en GitHub

1. Sube todos los archivos al repositorio `rodian0712/price-tracker`, manteniendo la ruta `.github/workflows/price_tracker.yml`.
2. En GitHub entra a **Settings → Secrets and variables → Actions → New repository secret** y crea:
   - `MAIL_USERNAME`: tu dirección Gmail completa.
   - `MAIL_TO`: dirección que recibirá el reporte (puede ser la misma).
   - `GMAIL_APP_PASSWORD`: contraseña de aplicación de Google, sin espacios.
3. Para Gmail, activa la verificación en dos pasos y crea una contraseña de aplicación desde la configuración de tu cuenta Google. No uses tu contraseña normal.
4. En **Settings → Actions → General → Workflow permissions**, habilita lectura y escritura si el repositorio no permite que el workflow actualice `prices.csv`. El workflow ya declara `contents: write`.
5. Entra a **Actions → Daily Price Tracker → Run workflow** para probarlo manualmente.
6. Revisa el log del workflow y tu correo. Si una tienda bloquea solicitudes o no publica precio estructurado, el correo lo indicará como `NO_PRICE_FOUND`.

## Ajustar los productos

Edita `products.json`. Cada entrada necesita una URL de la página concreta de producto. Para rastrear tamaños distintos del perfume, agrega una entrada por cada tamaño con su URL de variante exacta si la tienda ofrece enlaces diferentes. No dupliques la misma URL con tamaños diferentes: podría registrar el mismo precio para todos.

El tracker solo registra un valor en `price_clp` cuando la página declara la moneda `CLP`. Si una página publica otra moneda, conserva la moneda original y deja `price_clp` vacío; no convierte divisas automáticamente.

## Importante
- Los sitios pueden cambiar el HTML, bloquear automatizaciones o mostrar precios mediante JavaScript; por eso el scraping no está garantizado en todas las tiendas.
- Respeta los términos y límites de cada sitio. No intenta saltarse CAPTCHA ni medidas anti-bot.
- GitHub Actions para repositorios públicos usa runners estándar sin costo según la documentación de GitHub, sujeto a sus políticas y límites vigentes.
- La ejecución programada puede retrasarse. La hora del cron está en UTC y se eligió para aproximarse a las 09:00 de Santiago en horario de verano; no cambia automáticamente con la hora local.
- Nunca subas credenciales al repositorio ni las escribas en `products.json`.
