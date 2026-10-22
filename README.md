# Brief de 8h

E-mail matinal automatique qui résume l'état de votre VPS Ubuntu chaque jour ouvré à 08 h 00 UTC.

## Ce qui est vérifié

| Indicateur | Méthode |
|---|---|
| **Conteneurs Docker** | `docker ps -a` — vert si tous « Up », rouge sinon |
| **Mises à jour sécurité** | `apt` — vert si 0 correctif sécu, orange/rouge sinon |
| **Sauvegardes** | Restic (dernier snapshot) ou `/opt/backups` (date du fichier le plus récent) ; orange si aucune sauvegarde off-site configurée |
| **Chatwoot** | API REST — nombre de conversations ouvertes non lues |

## Installation

```bash
# Cloner le dépôt dans le dossier de vos services Docker
cd /var/www/docker
git clone https://github.com/<votre-org>/cursor-brief.git brief-8h
cd brief-8h

# Copier et remplir les variables d'environnement
cp .env.example .env
nano .env          # renseigner au minimum CHATWOOT_BASE_URL et CHATWOOT_API_TOKEN
```

Aucune dépendance externe : le script utilise uniquement la bibliothèque standard Python 3 (≥ 3.8).

## Variables d'environnement

| Variable | Obligatoire | Description |
|---|---|---|
| `CHATWOOT_BASE_URL` | oui | URL de votre instance Chatwoot |
| `CHATWOOT_API_TOKEN` | oui | Jeton API Chatwoot |
| `CHATWOOT_ACCOUNT_ID` | non | ID du compte Chatwoot (défaut : `1`) |
| `RESTIC_REPOSITORY` | non | Dépôt Restic (active la vérification off-site) |
| `RESTIC_PASSWORD` | non | Mot de passe du dépôt Restic |
| `BACKUP_DIR` | non | Dossier de backups locaux (défaut : `/opt/backups`) |
| `BRIEF_DETAIL_URL` | non | Lien du bouton « Voir le détail » |

> **Sécurité** : ne jamais commiter de secrets. Utilisez le fichier `.env` (ignoré par git) ou les variables d'environnement du système.

## Test rapide

```bash
# Charger les variables d'environnement
set -a && source .env && set +a

# Générer le brief dans un fichier
python3 brief_8h.py -o /tmp/brief.html

# Ou afficher sur stdout
python3 brief_8h.py --stdout
```

Ouvrez `/tmp/brief.html` dans un navigateur pour vérifier le rendu.

## Workflow n8n

1. Dans n8n, aller dans **Workflows → Importer depuis un fichier**.
2. Importer `n8n_workflow_brief_8h.json`.
3. Configurer le credential **SMTP Brief** avec vos paramètres SMTP.
4. Vérifier que le chemin dans le nœud « Exécuter brief_8h.py » correspond à votre installation.
5. Activer le workflow.

Le workflow est importé **inactif** par défaut. Il se déclenchera du lundi au vendredi à 08 h 00 UTC.

## Structure du projet

```
.
├── brief_8h.py                  # Script principal
├── templates/
│   └── brief.html               # Template HTML de l'e-mail
├── n8n_workflow_brief_8h.json   # Workflow n8n (inactif)
├── .env.example                 # Modèle de variables d'environnement
├── .gitignore
└── README.md                    # Ce fichier
```
