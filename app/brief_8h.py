#!/usr/bin/env python3
"""
Collecte les métriques du VPS et génère le brief matinal au format HTML.

Usage :
    python3 brief_8h.py              # écrit brief.html dans le dossier courant
    python3 brief_8h.py --stdout     # affiche le HTML sur stdout
    python3 brief_8h.py --post       # génère et POST vers le webhook n8n
"""

import argparse
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path


# Couleurs feu tricolore
OK = "#1a7f37"
WARN = "#b35900"
KO = "#c62828"

SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = SCRIPT_DIR / "templates" / "brief.html"


####################################################################
#                   Vérification des conteneurs                    #
####################################################################


def check_containers():
    """Vérifie que tous les conteneurs Docker sont « running »."""
    ignore_raw = os.environ.get("IGNORE_CONTAINERS", "listmonk_app,listmonk_db")
    ignored = {c.strip() for c in ignore_raw.split(",") if c.strip()}

    try:
        raw = subprocess.check_output(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            text=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return KO, "impossible d'interroger Docker"

    lines = [l for l in raw.strip().splitlines() if l]
    if not lines:
        return WARN, "aucun conteneur trouvé"

    not_running = []
    for line in lines:
        name, status = line.split("\t", 1)
        if name in ignored:
            continue
        lower_status = status.lower()
        if lower_status.startswith("up"):
            continue
        if "exited (0)" in lower_status:
            continue
        not_running.append(name)

    monitored = len([l for l in lines if l.split("\t", 1)[0] not in ignored])
    if not_running:
        return KO, f"{len(not_running)}/{monitored} arrêté(s) : {', '.join(not_running)}"
    return OK, f"{monitored}/{monitored} en cours d'exécution"


####################################################################
#                Mises à jour de sécurité (apt)                    #
####################################################################


def check_security_updates():
    """Compte les mises à jour de sécurité en attente via apt (sans sudo)."""
    try:
        raw = subprocess.check_output(
            ["apt", "list", "--upgradable"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return WARN, "impossible de vérifier (apt indisponible)"

    packages = [l for l in raw.splitlines() if "/" in l]
    security = [l for l in packages if "security" in l.lower()]

    if security:
        color = KO if len(security) > 10 else WARN
        return color, f"{len(security)} correctif(s) de sécurité sur {len(packages)} paquet(s)"
    if packages:
        return OK, f"{len(packages)} mise(s) à jour disponible(s), 0 sécurité"
    return OK, "système à jour"


####################################################################
#                  Sauvegardes (Restic / dossier)                  #
####################################################################


def check_backups():
    """Vérifie la fraîcheur de la dernière sauvegarde (Restic ou /opt/backups)."""
    now = datetime.now(timezone.utc)
    offsite = os.environ.get("RESTIC_REPOSITORY", "")

    # -- Restic ---------------------------------------------------
    if offsite:
        try:
            raw = subprocess.check_output(
                ["restic", "snapshots", "--json", "--latest", "1"],
                text=True,
                timeout=60,
            )
            snaps = json.loads(raw)
            if snaps:
                ts = snaps[0].get("time", "")
                snap_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                age_h = (now - snap_time).total_seconds() / 3600
                if age_h < 26:
                    return OK, f"Restic : dernier snapshot il y a {int(age_h)} h"
                return KO, f"Restic : dernier snapshot il y a {int(age_h)} h (> 24 h)"
        except (subprocess.SubprocessError, FileNotFoundError, (json.JSONDecodeError, IndexError, KeyError)):
            pass

    # -- Dossier local /opt/backups --------------------------------
    backup_dir = Path(os.environ.get("BACKUP_DIR", "/opt/backups"))
    if backup_dir.is_dir():
        entries = sorted(backup_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if entries:
            latest_mtime = datetime.fromtimestamp(entries[0].stat().st_mtime, tz=timezone.utc)
            age_h = (now - latest_mtime).total_seconds() / 3600
            status_color = OK if age_h < 26 else KO
            texte = f"dernier backup local il y a {int(age_h)} h"
            if not offsite:
                return WARN, f"{texte} (pas de sauvegarde off-site configurée)"
            return status_color, texte

    if not offsite:
        return WARN, "aucune sauvegarde off-site configurée"
    return KO, "aucun snapshot ou dossier de backup trouvé"


####################################################################
#           Conversations Chatwoot ouvertes                        #
####################################################################


def check_chatwoot():
    """Interroge /conversations/meta pour obtenir le nombre de conversations ouvertes."""
    base_url = os.environ.get("CHATWOOT_BASE_URL", "").rstrip("/")
    token = os.environ.get("CHATWOOT_API_TOKEN", "")
    account_id = os.environ.get("CHATWOOT_ACCOUNT_ID", "1")

    if not base_url or not token:
        return 0, "variables CHATWOOT_BASE_URL / CHATWOOT_API_TOKEN manquantes"

    url = f"{base_url}/api/v1/accounts/{account_id}/conversations/meta"
    req = urllib.request.Request(url, headers={
        "api_access_token": token,
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        meta = data.get("data", {}).get("meta", data.get("meta", {}))
        all_count = meta.get("all_count", 0)
        return all_count, None
    except (urllib.error.URLError, json.JSONDecodeError, KeyError) as exc:
        return 0, str(exc)


####################################################################
#                       Rendu du HTML                              #
####################################################################


def render(template_path: Path, values: dict) -> str:
    """Remplace les {{PLACEHOLDER}} par les valeurs collectées."""
    html = template_path.read_text(encoding="utf-8")
    for key, val in values.items():
        html = html.replace("{{" + key + "}}", str(val))
    return html


def compute_resume(cont_color, maj_color, backup_color):
    """Génère la phrase de résumé en tête du brief."""
    if cont_color == KO or maj_color == KO or backup_color == KO:
        return "un ou plusieurs points nécessitent votre attention."
    if cont_color == WARN or maj_color == WARN or backup_color == WARN:
        return "globalement OK, un point à surveiller."
    return "tout est au vert !"


####################################################################
#                    POST vers le webhook n8n                      #
####################################################################


LOG_MAX_BYTES = 1_048_576  # 1 Mo
LOG_BACKUP_COUNT = 4

log = logging.getLogger("brief_8h")


def setup_logging(logfile: Path | None = None):
    """Configure le logger : fichier rotatif en mode --post, stderr sinon."""
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    if logfile:
        handler = logging.handlers.RotatingFileHandler(
            logfile,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    else:
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(fmt)
    log.addHandler(handler)


def post_to_webhook(html: str):
    """Envoie le HTML au webhook n8n via urllib (pas besoin de curl/jq)."""
    webhook_url = os.environ.get(
        "BRIEF_WEBHOOK_URL",
        "http://127.0.0.1:5678/webhook/brief-8h",
    )
    secret = os.environ.get("BRIEF_WEBHOOK_SECRET", "")

    if not secret or secret.startswith("changez_moi"):
        log.error("BRIEF_WEBHOOK_SECRET non défini ou encore à sa valeur placeholder")
        sys.exit(1)

    payload = json.dumps({"html": html}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "X-Brief-Secret": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            log.info("OK POST %s → HTTP %s", webhook_url, resp.status)
    except urllib.error.HTTPError as exc:
        log.error("POST %s → HTTP %s %s", webhook_url, exc.code, exc.reason)
        sys.exit(1)
    except urllib.error.URLError as exc:
        log.error("POST %s → %s", webhook_url, exc.reason)
        sys.exit(1)


####################################################################
#                            Main                                  #
####################################################################


def main():
    parser = argparse.ArgumentParser(description="Brief de 8h — collecte et rendu HTML")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stdout", action="store_true", help="Afficher le HTML sur stdout")
    group.add_argument("--post", action="store_true", help="POST le HTML vers le webhook n8n")
    parser.add_argument("-o", "--output", default="brief.html", help="Fichier de sortie (défaut: brief.html)")
    args = parser.parse_args()

    if args.post:
        logfile = SCRIPT_DIR.parent / "brief.log"
        setup_logging(logfile)
    else:
        setup_logging()

    cont_color, cont_text = check_containers()
    maj_color, maj_text = check_security_updates()
    bkp_color, bkp_text = check_backups()
    cw_count, cw_err = check_chatwoot()

    if cw_err:
        cw_text = f"0 (⚠ {cw_err})"
    else:
        cw_text = str(cw_count)

    values = {
        "DATE": datetime.now().strftime("%d/%m/%Y"),
        "RESUME": compute_resume(cont_color, maj_color, bkp_color),
        "CONTENEURS_COULEUR": cont_color,
        "CONTENEURS_TEXTE": cont_text,
        "MAJ_COULEUR": maj_color,
        "MAJ_TEXTE": maj_text,
        "SAUVEGARDES_COULEUR": bkp_color,
        "SAUVEGARDES_TEXTE": bkp_text,
        "CHATWOOT_OUVERTES": cw_text,
    }

    html = render(TEMPLATE_PATH, values)

    if args.post:
        post_to_webhook(html)
    elif args.stdout:
        sys.stdout.write(html)
    else:
        Path(args.output).write_text(html, encoding="utf-8")
        print(f"✓ Brief généré → {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
