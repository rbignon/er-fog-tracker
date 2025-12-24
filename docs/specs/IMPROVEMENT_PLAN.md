# Plan d'Amélioration - Fog Gate Randomizer Tracker

Ce document présente les améliorations identifiées lors de l'audit de code de décembre 2024, organisées par phase de priorité.

## Vue d'ensemble

| Composant | État | Critiques | Moyens | Mineurs |
|-----------|------|-----------|--------|---------|
| Mod Rust | Bon | 4 | 6 | 4 |
| Serveur Python | Bon | 5 | 8 | 5 |
| Frontend JS | Bon | 3 | 7 | 5 |

---

## Phase 1 : Fixes Critiques

Corrections essentielles pour la stabilité et l'intégrité des données.

### 1.1 Frontend - Memory Leak Event Listeners

**Fichier:** `web/js/graph.js`

**Problème:** `renderGraph()` ajoute des `State.subscribe()` sans cleanup. Après N re-renders, N handlers s'exécutent pour chaque événement.

**Impact:** Ralentissement exponentiel après 30+ minutes d'utilisation.

**Solution:**
```javascript
let graphCleanups = [];

export function renderGraph(preservePositions = false) {
    // Cleanup des anciens subscriptions
    graphCleanups.forEach(fn => fn());
    graphCleanups = [];

    // ... code existant ...

    // Collecter les nouveaux subscriptions
    graphCleanups.push(
        State.subscribe('nodeTagsUpdated', callback),
        State.subscribe('searchMatched', callback),
        // etc.
    );
}
```

---

### 1.2 Frontend - Timeout sur les requêtes API

**Fichier:** `web/js/api.js`

**Problème:** `fetch()` peut bloquer indéfiniment si le réseau est dégradé.

**Solution:**
```javascript
async function apiFetch(path, options = {}, timeout = 30000) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);

    try {
        const response = await fetch(path, {
            ...options,
            signal: controller.signal,
            headers: { ... },
        });
        clearTimeout(timeoutId);
        return response;
    } catch (err) {
        clearTimeout(timeoutId);
        if (err.name === 'AbortError') {
            throw new Error(`Request timeout after ${timeout}ms`);
        }
        throw err;
    }
}
```

---

### 1.3 Frontend - Error Handling sur WebSocket Send

**Fichier:** `web/js/sync/host.js:54-59`

**Problème:** Si la sérialisation JSON échoue (référence circulaire), pas de log.

**Solution:**
```javascript
try {
    const state = getFullSyncState();
    const message = JSON.stringify({ type: 'visual_state', state });
    ws.send(message);
} catch (err) {
    console.error('Failed to sync state:', err);
} finally {
    isSyncing = false;
}
```

---

### 1.4 Serveur - Gestion des OAuth States

**Fichier:** `server/fogvizu/api/auth.py:24-40`

**Problème:** `_oauth_states.clear()` efface tous les states d'un coup, cassant les OAuth flows en cours.

**Solution:**
```python
import time

_oauth_states: dict[str, float] = {}  # state -> timestamp
STATE_TTL = 600  # 10 minutes

def _cleanup_old_states():
    cutoff = time.time() - STATE_TTL
    to_remove = [k for k, v in _oauth_states.items() if v < cutoff]
    for k in to_remove:
        del _oauth_states[k]

@router.get("/twitch")
async def auth_twitch_redirect():
    state = secrets.token_urlsafe(16)
    _oauth_states[state] = time.time()
    _cleanup_old_states()
    return RedirectResponse(url=get_twitch_oauth_url(state))
```

---

### 1.5 Serveur - Transaction Isolation pour Découvertes

**Fichier:** `server/fogvizu/websocket/mod.py:171-384`

**Problème:** Si deux mods envoient des découvertes en parallèle, une peut être perdue (race condition sur `discovered_zone_links`).

**Solution:** Ajouter un verrouillage optimiste avec colonne `version`.

1. Migration Alembic :
```python
def upgrade():
    op.add_column('games', sa.Column('version', sa.Integer, nullable=False, server_default='1'))
```

2. Dans le handler de découverte :
```python
async def handle_discovery(self, data: dict):
    async with async_session() as db:
        result = await db.execute(
            select(Game).where(Game.id == self.game_id).with_for_update()
        )
        game = result.scalar_one_or_none()

        # ... propagation ...

        game.version += 1
        await db.commit()
```

---

### 1.6 Mod - Timeout de Warp Pending

**Fichier:** `mod/src/tracker.rs:189-297`

**Problème:** Si un warp reste "pending" indéfiniment (crash pendant téléport), les données sont perdues.

**Solution:**
```rust
pub struct PendingWarp {
    entry: PlayerPosition,
    destination_entity_id: u32,
    transport_type: &'static str,
    created_at: Instant,  // Nouveau champ
}

const WARP_TIMEOUT: Duration = Duration::from_secs(30);

// Dans check_fog_traversal()
if let Some(ref pending) = self.pending_warp {
    if pending.created_at.elapsed() > WARP_TIMEOUT {
        warn!("Pending warp timed out, discarding");
        self.pending_warp = None;
    }
}
```

---

### 1.7 Mod - Messages d'Erreur WebSocket

**Fichier:** `mod/src/websocket.rs:567, 478, 481`

**Problème:** Échecs de parsing JSON silencieux, impossible de déboguer.

**Solution:**
```rust
// Ligne 567
match serde_json::from_str::<ServerResponse>(&text) {
    Ok(resp) => { /* handle */ }
    Err(e) => {
        warn!(error = %e, raw = %text, "[WS] Failed to parse server response");
    }
}

// Lignes 478, 481
_ => Err(format!("Unexpected response during auth: {:?}", resp)),
```

---

## Phase 2 : Fixes Importants

Améliorations de robustesse et performance.

### 2.1 Mod - Socket TLS Non-Bloquant

**Fichier:** `mod/src/websocket.rs:493-495`

**Problème:** Seules les connexions TCP plain sont configurées en non-bloquant.

**Impact:** Thread potentiellement bloqué sur lecture TLS.

**Solution:** Gérer les deux variants de `MaybeTlsStream`, ou utiliser `poll_msg()` avec timeout explicite.

---

### 2.2 Serveur - Validation des Noms de Zones

**Fichier:** `server/fogvizu/api/games.py`

**Problème:** Noms de zones acceptés sans validation (longueur, charset).

**Solution:**
```python
from pydantic import Field, validator

class ZoneLink(BaseModel):
    source: str = Field(..., max_length=255)
    target: str = Field(..., max_length=255)

    @validator('source', 'target')
    def validate_zone_name(cls, v):
        if not re.match(r"^[\w\s\-'(),]+$", v):
            raise ValueError(f"Invalid zone name format: {v}")
        return v
```

---

### 2.3 Serveur - Rate Limiting Viewers

**Fichier:** `server/fogvizu/websocket/viewer.py`

**Problème:** N'importe qui peut se connecter à n'importe quel `game_id` sans limite.

**Solution:** Ajouter rate limiting par IP avec `slowapi` ou middleware custom.

```python
from collections import defaultdict
import time

_viewer_connections: dict[str, list[float]] = defaultdict(list)
MAX_CONNECTIONS_PER_IP = 10
WINDOW_SECONDS = 60

def check_rate_limit(ip: str) -> bool:
    now = time.time()
    connections = _viewer_connections[ip]
    # Cleanup old entries
    connections[:] = [t for t in connections if now - t < WINDOW_SECONDS]
    if len(connections) >= MAX_CONNECTIONS_PER_IP:
        return False
    connections.append(now)
    return True
```

---

### 2.4 Frontend - Performance Placeholder Lookup

**Fichier:** `web/js/graph.js:287-324`

**Problème:** Utilisation de `.find()` (O(n)) pour chaque placeholder.

**Solution:**
```javascript
const placeholderIdSet = new Set();

// Au lieu de:
if (!placeholderNodes.find(n => n.id === placeholderIdForward))

// Utiliser:
if (!placeholderIdSet.has(placeholderIdForward)) {
    placeholderNodes.push({...});
    placeholderIdSet.add(placeholderIdForward);
}
```

---

### 2.5 Serveur - Index Base de Données

**Fichier:** `server/fogvizu/database.py`

**Problème:** Index manquant sur `Game.seed` et `Game.updated_at`.

**Solution:** Migration Alembic :
```python
def upgrade():
    op.create_index('idx_games_seed', 'games', ['seed'])
    op.create_index('idx_games_user_updated', 'games', ['user_id', 'updated_at'])
```

---

### 2.6 Mod - Augmenter Queue WebSocket

**Fichier:** `mod/src/websocket.rs:223-224`

**Problème:** Queue de 32 messages peut se remplir si le thread WebSocket est lent.

**Solution:**
```rust
let (outgoing_tx, outgoing_rx) = bounded::<OutgoingMessage>(128);
let (incoming_tx, incoming_rx) = bounded::<IncomingMessage>(128);
```

---

## Phase 3 : Améliorations de Qualité

Refactoring et améliorations non-critiques.

### 3.1 Serveur - Migration Nommage link_id

**Impact:** Serveur, potentiellement frontend.

**Tâches:**
1. Migration Alembic pour renommer dans les JSONB existants
2. Supprimer les alias de compatibilité dans `models.py`
3. Vérifier le frontend n'utilise pas `link_id`

---

### 3.2 Frontend - Constantes pour Timings

**Fichiers:** `web/js/graph.js`, `web/js/ui.js`

**Problème:** Valeurs magiques dispersées (100ms, 150ms, 300ms).

**Solution:**
```javascript
// web/js/constants.js
export const TIMING = {
    INITIAL_ZOOM_DELAY: 2000,
    POST_RENDER_SETUP: 100,
    HIGHLIGHT_SYNC: 150,
    CENTER_ON_NODE: 300,
};
```

---

### 3.3 Frontend - Indicateur de Chargement

**Fichier:** `web/js/main.js`

**Tâche:** Afficher un spinner pendant les appels API longs.

```javascript
function showLoading() {
    document.getElementById('main-ui').innerHTML =
        '<div class="loading-spinner"></div>';
}

async function initPlayMode(gameId) {
    showLoading();
    try {
        const game = await getGame(gameId);
        // ... render
    } catch (e) {
        showError(e.message);
    }
}
```

---

### 3.4 Mod - Logger Version du Jeu

**Fichier:** `mod/src/game_state.rs:351-364`

**Tâche:** Ajouter un log au démarrage indiquant la version détectée.

```rust
info!(
    version = ?version,
    player_ins_offset = %player_ins_offset,
    "Game version detected"
);
```

---

### 3.5 Serveur - Structured Logging

**Tâche:** Migrer vers `structlog` pour logs JSON cohérents.

```python
import structlog

logger = structlog.get_logger()
logger.info("discovery_processed", game_id=str(game_id), source=source, target=target)
```

---

## Phase 4 : Évolutions Futures

Améliorations à considérer pour une version ultérieure.

### 4.1 Tests d'Intégration

Ajouter des tests pytest-asyncio pour les scénarios de race condition :
- Découvertes parallèles
- Reconnexion WebSocket pendant sync
- OAuth flow complet

### 4.2 TypeScript

Migration du frontend vers TypeScript pour bénéficier du typage statique. Changement conséquent nécessitant :
- Configuration tsconfig.json
- Bundler (esbuild, vite)
- Migration progressive des fichiers

### 4.3 Monitoring

- Métriques Prometheus pour WebSocket (connexions, latence)
- Dashboard Grafana
- Alerting sur erreurs critiques

---

## Estimation d'Effort

| Phase | Effort Estimé | Priorité |
|-------|---------------|----------|
| Phase 1 | 4-6h | Haute |
| Phase 2 | 4-6h | Moyenne |
| Phase 3 | 4-6h | Basse |
| Phase 4 | Variable | Future |

---

## Changelog

- **2024-12-24** : Création initiale suite à l'audit de code
