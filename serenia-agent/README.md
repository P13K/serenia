# Serenia

> Agent de sauvegarde conteneurisé pour NAS — chiffrement de bout en bout, stockage souverain OVHcloud, configuration 100% via interface web.

**Toute la configuration se fait dans le navigateur** — aucun fichier à éditer à la main au-delà du mot de passe d'accès.

---

## Pourquoi Serenia ?

Les applications natives des NAS (Cloud Backup Center d'Asustor, Cloud Sync de Synology) pointent par défaut vers AWS, Azure ou Alibaba. Serenia propose une alternative européenne :

| | Serenia | Cloud Backup Center |
|---|---|---|
| Hébergement | OVHcloud (FR, DE, IT, PL, UK, CA…) | AWS / Azure / Alibaba |
| Chiffrement | Côté client, avant transfert | Côté serveur (provider voit les données) |
| Config | Interface web en français | Multiple fichiers et menus techniques |
| Vérification | Test de restauration hebdomadaire | Manuel |
| Egress | Inclus OVHcloud | Facturé chez les hyperscalers |

---

## Prérequis

- NAS avec **Docker + Docker Compose** (Asustor ADM ≥ 4.x, Synology DSM ≥ 7.2, ou Linux)
- Compte [OVHcloud](https://www.ovhcloud.com/) avec un projet Public Cloud
- Un **bucket Object Storage S3** créé dans le manager OVH
- Port **8765** disponible sur le NAS (modifiable)

---

## Installation

### 1. Cloner le dépôt sur le NAS

```bash
cd /volume1          # ou tout emplacement de votre choix
git clone https://github.com/P13K/serenia.git
cd serenia/serenia-agent
```

### 2. Configurer le fichier `.env`

```bash
cp .env.example .env
nano .env
```

Deux choses à remplir :
- `SERENIA_PASSWORD` — le mot de passe de l'interface web (**obligatoire**)
- `SERENIA_USER` — l'identifiant (défaut : `admin`)

Le reste de la configuration (identifiants OVH, bucket, passphrase de chiffrement, sources) se fait depuis l'interface web.

### 3. Lancer

```bash
sudo docker compose build
sudo docker compose up -d
```

La première construction prend 3 à 5 minutes (téléchargement des dépendances). Les relances suivantes sont quasi instantanées.

### 4. Ouvrir la webUI

```
http://<ip-du-nas>:8765
```

Le navigateur vous demande le mot de passe configuré dans `.env`. Serenia détecte qu'il n'est pas encore configuré et affiche le wizard en 4 étapes :

1. **OVHcloud** — région, bucket, access key, secret key + test de connexion
2. **Chiffrement** — Serenia génère une passphrase (ou utilisez la vôtre)
3. **Sources** — sélection des dossiers à sauvegarder
4. **Validation** — vérification complète + activation

### 5. Vérifier

```bash
sudo docker compose logs -f
# Ctrl+C pour quitter
```

---

## Régions OVHcloud disponibles

| Code | Ville | Pays |
|---|---|---|
| `eu-west-par` | Paris 3-AZ ★ | 🇫🇷 France |
| `gra` | Gravelines | 🇫🇷 France |
| `rbx` | Roubaix | 🇫🇷 France |
| `sbg` | Strasbourg | 🇫🇷 France |
| `de` | Francfort | 🇩🇪 Allemagne |
| `waw` | Varsovie | 🇵🇱 Pologne |
| `uk` | Londres | 🇬🇧 Royaume-Uni |
| `it` | Milan | 🇮🇹 Italie |
| `bhs` | Beauharnois | 🇨🇦 Canada |
| `t` | Toronto | 🇨🇦 Canada |

---

## Utilisation quotidienne

### Depuis l'interface web

- **Tableau de bord** — état des sauvegardes, coût mensuel estimé, ribbon 90 jours
- **Lancer une sauvegarde** — bouton en haut à droite
- **Ajouter/retirer une source** — depuis le tableau des sources
- **Onglet Stockage OVH** — comparatif des classes tarifaires avec simulateur

### Depuis la CLI (dépannage)

```bash
# Voir les logs en direct
sudo docker compose logs -f

# Forcer une sauvegarde immédiate
curl -u admin:VotreMotDePasse http://localhost:8765/api/backup -X POST

# Lister les snapshots restic
sudo docker compose exec serenia restic snapshots

# Restauration manuelle
sudo docker compose exec serenia restic restore latest --target /tmp/restore
```

---

## Sécurité

- **Mot de passe** : défini dans `.env` via `SERENIA_PASSWORD`. Sans lui, l'interface est accessible librement — à éviter en dehors d'un LAN isolé.
- **Secrets** : le fichier `config/config.json` contient vos identifiants OVH et la passphrase de chiffrement. Il est chmod 600 et ignoré par git.
- **Passphrase** : sans elle, vos sauvegardes sont définitivement illisibles. Notez-la dans un gestionnaire de mots de passe (Bitwarden, 1Password).
- **Réseau** : n'exposez pas le port 8765 directement sur Internet. Utilisez un VPN ou un reverse proxy avec TLS.

---

## Structure du projet

```
serenia-agent/
├── docker-compose.yml       # Orchestration
├── Dockerfile               # Image Python 3.12 Debian + restic
├── .env.example             # Modèle — copier en .env
├── app/
│   ├── main.py              # Backend FastAPI + scheduler
│   ├── requirements.txt
│   └── static/
│       ├── setup.html       # Wizard de configuration
│       └── dashboard.html   # Tableau de bord
├── config/                  # Runtime — secrets (gitignored)
└── logs/                    # Runtime — logs (gitignored)
```

---

## Roadmap

- [x] **v0.1** — Wizard web, dashboard, scheduler, auth basique, onglet coûts
- [ ] **v0.2** — Restauration guidée depuis la webUI
- [ ] **v0.3** — Object Lock (immutabilité anti-ransomware)
- [ ] **v0.4** — Support Synology DSM documenté et testé
- [ ] **v0.5** — Notifications (email, webhook)

---

## Licence

MIT — voir [LICENSE](./LICENSE).

_Serenia est un projet indépendant, non affilié à OVHcloud, Asustor ou Synology._
