# Brief de 8h

E-mail matinal automatique qui résume l'état de votre VPS Ubuntu chaque jour ouvré à 08 h 00 UTC.

## Ce qui est vérifié

| Indicateur | Méthode |
|---|---|
| **Conteneurs Docker** | `docker ps -a` — vert si tous « Up » (ignore les `Exited (0)` et les conteneurs listés dans `IGNORE_CONTAINERS`) |
| **Mises à jour sécurité** | `apt list --upgradable` — vert si 0 correctif sécu, orange/rouge sinon (pas besoin de root) |
| **Sauvegardes** | Restic (dernier snapshot) ou `/opt/backups` (date du fichier le plus récent) ; orange si aucune sauvegarde off-site configurée |
| **Chatwoot** | API `/conversations/meta` — nombre de conversations ouvertes |

## Architecture

```
┌──────────────────────────────────┐       POST /webhook/brief-8h      ┌──────────────────┐
│  Cron host (user equipe)         │  ──────────────────────────────▶  │  n8n (conteneur)  │
│  python3 brief_8h.py --post      │    Header: X-Brief-Secret         │  Webhook → SMTP   │
│  (urllib, zéro dépendance)       │                                   │  → henoc@…         │
└──────────────────────────────────┘                                   └──────────────────┘
```

Le script tourne **sur l'hôte** (accès direct à Docker, apt, backups). Avec `--post`, il génère le HTML et le POST lui-même vers le webhook n8n via `urllib` (aucune dépendance externe). Pas de SSH ni d'Execute Command dans le conteneur.

## Installation

```bash
# Cloner le dépôt
cd /var/www/docker
git clone https://github.com/<votre-org>/cursor-brief.git brief
cd brief/app

# Copier et remplir les variables d'environnement
cp .env.example ../.env
nano ../.env       # renseigner au minimum CHATWOOT_BASE_URL, CHATWOOT_API_TOKEN et BRIEF_WEBHOOK_SECRET
```

Aucune dépendance externe : le script utilise uniquement la bibliothèque standard Python 3 (≥ 3.8).

## Variables d'environnement

Le fichier `.env` se place dans `/var/www/docker/brief/.env` (un niveau au-dessus de `app/`).

| Variable | Obligatoire | Description |
|---|---|---|
| `CHATWOOT_BASE_URL` | oui | URL de votre instance Chatwoot |
| `CHATWOOT_API_TOKEN` | oui | Jeton API Chatwoot |
| `CHATWOOT_ACCOUNT_ID` | non | ID du compte Chatwoot (défaut : `1`) |
| `BRIEF_WEBHOOK_SECRET` | oui | Secret partagé avec le webhook n8n (header `X-Brief-Secret`) |
| `BRIEF_WEBHOOK_URL` | non | URL du webhook n8n (défaut : `http://127.0.0.1:5678/webhook/brief-8h`) |
| `IGNORE_CONTAINERS` | non | Conteneurs à exclure du monitoring, séparés par des virgules (défaut : `listmonk_app,listmonk_db`) |
| `RESTIC_REPOSITORY` | non | Dépôt Restic (active la vérification off-site) |
| `RESTIC_PASSWORD` | non | Mot de passe du dépôt Restic |
| `BACKUP_DIR` | non | Dossier de backups locaux (défaut : `/opt/backups`) |

> **Sécurité** : ne jamais commiter de secrets. Utilisez le fichier `.env` (ignoré par git) ou les variables d'environnement du système.

## Crontab (user `equipe`)

Ajouter la ligne suivante avec `crontab -e` :

```cron
0 8 * * 1-5 cd /var/www/docker/brief/app && set -a && . ../.env && set +a && python3 brief_8h.py --post
```

Détail :
1. Charge les variables depuis `../.env`
2. Exécute le script qui collecte les métriques, génère le HTML et le POST directement vers le webhook n8n
3. Les logs (succès ou erreur, horodatés) sont écrits dans `../brief.log` avec rotation automatique

## Logs

En mode `--post`, le script écrit dans `/var/www/docker/brief/brief.log` via un `RotatingFileHandler` (stdlib) :
- **1 Mo** par fichier, **4 fichiers** de rétention (`brief.log.1` … `brief.log.4`)
- Pas besoin de `logrotate`, pas besoin de `sudo`
- Pour consulter les dernières exécutions : `tail -30 /var/www/docker/brief/brief.log`

## Test rapide

```bash
# Charger les variables d'environnement
cd /var/www/docker/brief/app
set -a && . ../.env && set +a

# 1. Vérifier la génération du HTML
python3 brief_8h.py --stdout > /tmp/brief.html
# Ouvrir /tmp/brief.html dans un navigateur pour vérifier le rendu

# 2. Tester l'envoi complet (workflow n8n activé requis)
python3 brief_8h.py --post
```

## Workflow n8n

1. Dans n8n, aller dans **Workflows → Importer depuis un fichier**.
2. Importer `n8n_workflow_brief_8h.json`.
3. Créer un credential **Header Auth** : nom `Brief Header Auth`, header `X-Brief-Secret`, valeur = celle de `BRIEF_WEBHOOK_SECRET` dans `.env`.
4. Configurer le credential **SMTP Brief** avec vos paramètres SMTP.
5. Activer le workflow.

Le workflow est importé **inactif** par défaut. Il accepte les requêtes POST sur `/webhook/brief-8h` et envoie l'e-mail depuis `brief@dekaeditions.tg`.

## Structure du projet

```
.
├── app/
│   ├── brief_8h.py                  # Script principal
│   └── templates/
│       └── brief.html               # Template HTML de l'e-mail
├── n8n_workflow_brief_8h.json       # Workflow n8n (inactif)
├── .env.example                     # Modèle de variables d'environnement
├── .gitignore
├── README.md                        # Ce fichier
└── brief.log                        # Logs (généré, ignoré par git)
```
