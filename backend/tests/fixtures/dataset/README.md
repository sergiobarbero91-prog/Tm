# Ticket OCR Ground-Truth Dataset

Estructura preparada para incorporar fotografías reales de tickets y sus valores correctos, para poder medir la exactitud del OCR de forma cuantitativa (paso 21 del prompt del usuario).

## Estructura

```
dataset/
├── README.md         (este archivo)
├── images/           <- fotografías reales (JPG/PNG/WEBP/HEIC)
│   ├── 001.jpg
│   ├── 002.jpg
│   └── ...
└── ground_truth/     <- valores correctos verificados a mano
    ├── 001.json
    ├── 002.json
    └── ...
```

## Formato del JSON

Cada `ground_truth/NNN.json` debe emparejarse con `images/NNN.<ext>` y contener los
valores REALES que el OCR debería extraer. Ejemplo:

```json
{
  "image": "001.jpg",
  "notes": "Foto con sombra parcial en la esquina superior derecha.",
  "fields": {
    "fecha":         {"date": "2026-09-20", "time": "15:03"},
    "licencia":      "09218",
    "num_servicios": 5606,
    "carreras":      "60854.75",
    "suplementos":   "204.90",
    "total":         "61059.65",
    "dist_total":    "52537.90",
    "dist_ocupado":  "25457.10",
    "dist_libre":    "26742.50",
    "dist_off":      "339.00",
    "tiempo_ocupado": 55761,
    "tiempo_on":      156015,
    "borrados":       454
  }
}
```

* Los importes y distancias se anotan como **strings** con punto decimal para
  poder compararlos con precisión de Decimal en los tests.
* Los enteros (num_servicios, tiempos, borrados, licencia) van como enteros
  o como strings con ceros a la izquierda (licencia).
* Cualquier campo que no aparezca en la foto se omite (o se pone `null`).

## Cómo se usan estas fotos en los tests

`backend/tests/test_ticket_dataset.py` (aún no incluido; ver ROADMAP) itera
por todas las parejas `image + JSON` y ejecuta `scan_taxitronic_ticket`.
Para cada campo compara la salida con la verdad-terreno y reporta 4 métricas:

| Métrica              | Definición                                                    |
|----------------------|---------------------------------------------------------------|
| accuracy             | % de campos con valor correcto (independiente del status).    |
| false_acceptance     | % de campos con `status=accepted` pero valor incorrecto.      |
| needs_confirmation   | % de campos marcados `needs_confirmation` por el pipeline.    |
| coverage             | % de campos del ground-truth que llegaron a extraerse.        |

**La métrica CRÍTICA es `false_acceptance`**: cuánto vale la promesa de
"no invento datos". Debe ser 0 — cualquier valor > 0 es un bug.

## Anonimización

Antes de commitear fotos, borra:
- Nombre y matrícula del conductor.
- QR codes o códigos de barras que identifiquen al taxista.
- Cualquier dato personal impreso al pie del ticket.

Si la foto tiene datos personales, guárdala fuera del repositorio y
referencia sólo el JSON del ground-truth en `expected/` sin la imagen.
