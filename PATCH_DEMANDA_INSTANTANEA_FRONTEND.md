# Parche Frontend — Demanda en este Momento

Añade esto en `frontend/app/index.tsx` de tu servidor SIN modificar nada más
de la sección de aviones (P/E/F/S, GRANDES, DEMANDA, Cinta, etc., todo intacto).

---

## 1. Añade los campos al interface TerminalData

Busca el interface `TerminalData` (alrededor de línea ~180) y añade estas líneas
al final del interface, antes del `}`:

```ts
  // Demanda en este Momento (nuevo)
  instant_demand_pct?: number;
  instant_demand_level?: 'green' | 'yellow' | 'red' | 'critical';
  instant_demand_trend?: 'up' | 'down' | 'flat';
}
```

---

## 2. En `renderTerminalCard` añade la agregación

Busca tu función `renderTerminalCard` (que ya tiene la lógica P/E/F/S/GRANDES/DEMANDA).
Localiza el `group.terminals.forEach(...)` y añade DENTRO del bucle, debajo de las
demás sumas, este bloque:

```ts
let instantPctSum = 0;
let instantTrendUp = 0;
let instantTrendDown = 0;
let instantHasData = false;

group.terminals.forEach(terminalName => {
  const terminal = flightData.terminals[terminalName];
  if (terminal) {
    // ... tu código actual de sumas P/E/F/S/grandes ...

    // === AÑADE ESTO al final del bloque ===
    if (typeof terminal.instant_demand_pct === 'number') {
      instantHasData = true;
      instantPctSum += terminal.instant_demand_pct;
      if (terminal.instant_demand_trend === 'up') instantTrendUp += 1;
      else if (terminal.instant_demand_trend === 'down') instantTrendDown += 1;
    }
  }
});

// === Después del forEach añade ===
const instantPct = instantHasData ? Math.round(instantPctSum / group.terminals.length) : null;
const instantColor =
  instantPct === null ? '#10B981' :
  instantPct > 100 ? '#DC2626' :
  instantPct >= 70 ? '#EF4444' :
  instantPct >= 40 ? '#F59E0B' :
  '#10B981';
const instantTrend: 'up' | 'down' | 'flat' = !instantHasData ? 'flat' :
  instantTrendUp > instantTrendDown ? 'up' :
  instantTrendDown > instantTrendUp ? 'down' : 'flat';
```

---

## 3. Pega la NUEVA barra en el JSX

Localiza dentro del JSX de la tarjeta de terminal el sitio justo **DESPUÉS** del
`Score: X.X` chip y **ANTES** del cierre de la tarjeta (donde están los botones
"Sin taxis" / "Barandilla" en tu pantalla).

Pega esto entre ambos:

```tsx
{/* === NUEVA: Demanda en este Momento === */}
{instantPct !== null && (
  <View
    testID={`instant-demand-${group.terminals[0]}`}
    style={{
      marginTop: 10,
      paddingTop: 10,
      borderTopWidth: 1,
      borderTopColor: 'rgba(99, 102, 241, 0.15)',
    }}
  >
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flex: 1 }}>
        <Ionicons name="pulse" size={14} color={instantColor} />
        <Text style={{ color: '#94A3B8', fontSize: 12, fontWeight: '600', marginRight: 8 }}>
          Demanda en este Momento
        </Text>
      </View>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Text style={{ color: instantColor, fontSize: 14, fontWeight: '800' }}>
          {instantPct}%
        </Text>
        <Ionicons
          name={instantTrend === 'up' ? 'arrow-up' : instantTrend === 'down' ? 'arrow-down' : 'remove'}
          size={14}
          color={instantTrend === 'up' ? '#EF4444' : instantTrend === 'down' ? '#10B981' : '#64748B'}
        />
      </View>
    </View>
    <View style={{
      width: '100%',
      height: 8,
      backgroundColor: 'rgba(100, 116, 139, 0.18)',
      borderRadius: 4,
      overflow: 'hidden',
    }}>
      <View style={{
        height: '100%',
        width: `${Math.min(instantPct, 100)}%`,
        backgroundColor: instantColor,
        borderRadius: 4,
      }} />
      {instantPct > 100 && (
        <View style={{
          position: 'absolute', right: 2, top: 1, bottom: 1,
          width: 4, backgroundColor: '#FCA5A5', borderRadius: 2,
        }} />
      )}
    </View>
  </View>
)}
```

---

## ✅ Resultado

Tu pantalla actual de Aviones queda **IGUAL** salvo que debajo del chip `Score: 2.0`
aparece una nueva barra con:
- Etiqueta "Demanda en este Momento"
- Porcentaje (verde<40% / amarillo 40-70% / rojo 70-100% / rojo intenso >100%)
- Flecha de tendencia ⬆ / ⬇ / ➡
- Barra de progreso coloreada

Sin tocar nada de la barra DEMANDA con escala Baja/Media/Alta que ya tenías arriba.
