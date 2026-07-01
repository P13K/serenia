"""
Sérénia Agent — Backend FastAPI
Une seule webUI pour configurer, planifier et piloter les sauvegardes.
"""
import os
import json
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Optional

import secrets
import base64
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from pydantic import BaseModel, Field

# ─── Auth basique ────────────────────────────────────────────────
SERENIA_PASSWORD = os.environ.get("SERENIA_PASSWORD", "")
SERENIA_USER = os.environ.get("SERENIA_USER", "admin")

def check_auth(request: Request):
    if not SERENIA_PASSWORD:
        return
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Authentification requise",
            headers={"WWW-Authenticate": 'Basic realm="Serenia"'},
        )
    try:
        decoded = base64.b64decode(auth[6:]).decode("utf-8")
        user, pwd = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Format invalide",
                            headers={"WWW-Authenticate": 'Basic realm="Serenia"'})
    if not (secrets.compare_digest(user, SERENIA_USER) and
            secrets.compare_digest(pwd, SERENIA_PASSWORD)):
        raise HTTPException(status_code=401, detail="Identifiants incorrects",
                            headers={"WWW-Authenticate": 'Basic realm="Serenia"'})

AuthDep = Depends(check_auth)

# ─── Chemins persistants ─────────────────────────────────────────
CONFIG_DIR = Path("/etc/serenia")
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_FILE = CONFIG_DIR / "state.json"
LOG_DIR = Path("/var/log/serenia")
STATIC_DIR = Path("/app/static")
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ─── Modèle de configuration ────────────────────────────────────
class Config(BaseModel):
    ovh_access_key: str
    ovh_secret_key: str
    ovh_region: str = "eu-west-par"
    ovh_endpoint: str = "s3.eu-west-par.io.cloud.ovh.net"
    ovh_bucket: str
    restic_password: str
    sources: List[str] = Field(default_factory=list)
    hostname: str = "nas"
    keep_daily: int = 7
    keep_weekly: int = 4
    keep_monthly: int = 6
    schedule_hour: int = 3
    initialized: bool = False


class TestPayload(BaseModel):
    """Test S3 uniquement — pas besoin de passphrase."""
    ovh_access_key: str
    ovh_secret_key: str
    ovh_region: str = "eu-west-par"
    ovh_endpoint: str = "s3.eu-west-par.io.cloud.ovh.net"
    ovh_bucket: str


class ValidatePayload(BaseModel):
    """Validation complète (S3 + restic + passphrase)."""
    ovh_access_key: str
    ovh_secret_key: str
    ovh_region: str = "eu-west-par"
    ovh_endpoint: str = "s3.eu-west-par.io.cloud.ovh.net"
    ovh_bucket: str
    restic_password: str


def load_config() -> Optional[Config]:
    if not CONFIG_FILE.exists():
        return None
    try:
        return Config(**json.loads(CONFIG_FILE.read_text()))
    except Exception:
        return None


def save_config(cfg: Config) -> None:
    CONFIG_FILE.write_text(cfg.model_dump_json(indent=2))
    CONFIG_FILE.chmod(0o600)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def restic_env(cfg: Config) -> dict:
    return {
        **os.environ,
        "AWS_ACCESS_KEY_ID": cfg.ovh_access_key,
        "AWS_SECRET_ACCESS_KEY": cfg.ovh_secret_key,
        "AWS_DEFAULT_REGION": cfg.ovh_region,
        "RESTIC_REPOSITORY": f"s3:https://{cfg.ovh_endpoint}/{cfg.ovh_bucket}",
        "RESTIC_PASSWORD": cfg.restic_password,
    }


def restic_run(cfg: Config, args: List[str], timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["restic"] + args,
        env=restic_env(cfg),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ─── FastAPI ────────────────────────────────────────────────────
app = FastAPI(title="Sérénia", docs_url=None, redoc_url=None)


@app.get("/", response_class=HTMLResponse)
def index(_auth=AuthDep):
    cfg = load_config()
    if not cfg or not cfg.initialized:
        return RedirectResponse("/setup", status_code=302)
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/setup", response_class=HTMLResponse)
def setup(_auth=AuthDep):
    return FileResponse(STATIC_DIR / "setup.html")


# ─── API : lister les dossiers du NAS ───────────────────────────
@app.get("/api/browse")
def browse(_auth=AuthDep):
    root = Path("/volume1")
    if not root.exists():
        return {"folders": []}
    folders = []
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        # Estimation rapide de la taille (limitée aux 5000 premiers fichiers)
        size = 0
        try:
            for i, f in enumerate(p.rglob("*")):
                if i > 5000:
                    break
                if f.is_file():
                    try:
                        size += f.stat().st_size
                    except (PermissionError, FileNotFoundError, OSError):
                        pass
        except (PermissionError, OSError):
            pass
        folders.append({
            "path": str(p),
            "size_gb": round(size / 1e9, 2),
            "size_display": f"{size / 1e9:.1f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB",
        })
    return {"folders": folders}


# ─── API : tester la connexion OVH ──────────────────────────────
class TestS3Payload(BaseModel):
    ovh_access_key: str
    ovh_secret_key: str
    ovh_region: str = "eu-west-par"
    ovh_endpoint: str = "s3.eu-west-par.io.cloud.ovh.net"
    ovh_bucket: str


@app.post("/api/test-s3")
def test_s3(p: TestS3Payload, _auth=AuthDep):
    """
    Étape 1 du wizard : vérifie UNIQUEMENT que les credentials S3 atteignent
    le bucket. Pas besoin de la passphrase ici. On utilise restic avec un
    mot de passe bidon — l'erreur renvoyée nous dit tout :
      - "wrong password" / "no key found" → S3 OK, dépôt existant
      - "Is there a repository" → S3 OK, bucket vide (pas encore de dépôt)
      - "Access Denied" → credentials S3 invalides ou pas de droit sur le bucket
    """
    cfg = Config(
        ovh_access_key=p.ovh_access_key,
        ovh_secret_key=p.ovh_secret_key,
        ovh_region=p.ovh_region,
        ovh_endpoint=p.ovh_endpoint,
        ovh_bucket=p.ovh_bucket,
        restic_password="__dummy_test_password__",
        sources=[],
        hostname="test",
    )
    r = restic_run(cfg, ["snapshots", "--json"], timeout=30)
    err = (r.stderr or "").lower()

    # Cas 1 : S3 OK, dépôt existant (passphrase bidon → wrong password, c'est attendu)
    if "wrong password" in err or "no key found" in err:
        return {"ok": True, "repo_exists": True,
                "message": "Connexion validée. Un dépôt existant a été détecté sur ce bucket."}

    # Cas 2 : S3 OK, résultat inattendu mais succès (ne devrait pas arriver avec un pwd bidon)
    if r.returncode == 0:
        return {"ok": True, "repo_exists": True,
                "message": "Connexion validée. Dépôt existant accessible."}

    # Cas 3 : S3 OK, pas de dépôt
    if "is there a repository" in err or "config file does not exist" in err:
        return {"ok": True, "repo_exists": False,
                "message": "Connexion validée. Bucket vide — Sérénia y créera un nouveau dépôt."}

    # Cas 4 : Erreur d'accès S3
    if "access denied" in err or "forbidden" in err:
        return {"ok": False,
                "error": "Accès refusé. Vérifiez vos clés S3 et que l'utilisateur a le rôle ObjectStore operator sur ce bucket."}

    # Cas 5 : Autre erreur (réseau, endpoint incorrect, etc.)
    last_line = (r.stderr or "").strip().split("\n")[-1]
    return {"ok": False, "error": last_line or "Connexion impossible. Vérifiez l'endpoint et vos identifiants."}


@app.post("/api/test-connection")
def test_connection(p: TestPayload, _auth=AuthDep):
    """
    Étape finale du wizard : vérifie que la passphrase est correcte pour
    un dépôt existant, ou initialise un nouveau dépôt si le bucket est vide.
    """
    cfg = Config(
        **p.model_dump(),
        sources=[],
        hostname="test",
    )
    # Tentative avec la vraie passphrase
    r = restic_run(cfg, ["snapshots", "--json"], timeout=30)
    if r.returncode == 0:
        count = 0
        try:
            count = len(json.loads(r.stdout) or [])
        except Exception:
            pass
        return {"ok": True, "message": f"Dépôt existant retrouvé — {count} snapshot(s) disponible(s)."}

    err = (r.stderr or "").lower()

    # Mauvaise passphrase sur un dépôt existant
    if "wrong password" in err or "no key found" in err:
        return {"ok": False, "error": "La passphrase ne correspond pas au dépôt existant sur ce bucket. Vérifiez votre saisie."}

    # Pas de dépôt → on en crée un
    if "is there a repository" in err or "config file does not exist" in err:
        r_init = restic_run(cfg, ["init"], timeout=30)
        if r_init.returncode == 0:
            return {"ok": True, "message": "Nouveau dépôt créé avec succès."}
        init_err = (r_init.stderr or "").strip().split("\n")[-1]
        return {"ok": False, "error": init_err or "Impossible de créer le dépôt."}

    last_line = (r.stderr or "").strip().split("\n")[-1]
    return {"ok": False, "error": last_line or "Erreur inattendue."}


# ─── API : enregistrer la configuration ─────────────────────────
@app.post("/api/config")
def save_config_endpoint(cfg: Config, _auth=AuthDep):
    # S'assure que le dépôt existe (init si besoin)
    r = restic_run(cfg, ["snapshots", "--json"], timeout=30)
    if r.returncode != 0:
        r_init = restic_run(cfg, ["init"], timeout=30)
        if r_init.returncode != 0:
            raise HTTPException(400, r_init.stderr.strip() or "Impossible d'initialiser le dépôt")

    cfg.initialized = True
    save_config(cfg)
    return {"ok": True}


# ─── API : statut global ────────────────────────────────────────
@app.get("/api/status")
def status(_auth=AuthDep):
    cfg = load_config()
    if not cfg or not cfg.initialized:
        return {"configured": False}

    r = restic_run(cfg, ["snapshots", "--json"], timeout=30)
    snapshots = []
    if r.returncode == 0:
        try:
            snapshots = json.loads(r.stdout) or []
        except Exception:
            snapshots = []

    # Taille du dépôt pour calcul de coût
    repo_size_bytes = None
    r_stats = restic_run(cfg, ["stats", "--json"], timeout=60)
    if r_stats.returncode == 0:
        try:
            stats_data = json.loads(r_stats.stdout)
            repo_size_bytes = stats_data.get("total_size")
        except Exception:
            pass

    state = load_state()

    return {
        "configured": True,
        "hostname": cfg.hostname,
        "region": cfg.ovh_region,
        "endpoint": cfg.ovh_endpoint,
        "bucket": cfg.ovh_bucket,
        "sources": cfg.sources,
        "snapshots_count": len(snapshots),
        "last_snapshots": snapshots[-20:] if snapshots else [],
        "last_backup_at": state.get("last_backup_at"),
        "last_backup_status": state.get("last_backup_status"),
        "schedule_hour": cfg.schedule_hour,
        "repo_size_bytes": repo_size_bytes,
    }


# ─── API : lancer un backup à la demande ────────────────────────
@app.post("/api/backup")
async def backup_now(_auth=AuthDep):
    cfg = load_config()
    if not cfg or not cfg.initialized:
        raise HTTPException(400, "Sérénia n'est pas encore configurée")
    return await _run_backup(cfg, tag="manual")


async def _run_backup(cfg: Config, tag: str = "auto") -> dict:
    """Lance un backup pour toutes les sources configurées."""
    started = datetime.now().isoformat()
    results = []
    all_ok = True
    for src in cfg.sources:
        if not Path(src).exists():
            results.append({"source": src, "success": False, "error": "chemin introuvable"})
            all_ok = False
            continue
        try:
            r = await asyncio.to_thread(
                restic_run, cfg,
                ["backup", src, "--tag", tag, "--host", cfg.hostname],
                3600
            )
            results.append({
                "source": src,
                "success": r.returncode == 0,
                "output": (r.stdout or r.stderr)[-500:],
            })
            if r.returncode != 0:
                all_ok = False
        except Exception as e:
            results.append({"source": src, "success": False, "error": str(e)})
            all_ok = False

    # Rétention
    if all_ok:
        try:
            await asyncio.to_thread(
                restic_run, cfg,
                ["forget",
                 "--keep-daily", str(cfg.keep_daily),
                 "--keep-weekly", str(cfg.keep_weekly),
                 "--keep-monthly", str(cfg.keep_monthly),
                 "--prune"],
                600
            )
        except Exception:
            pass

    state = load_state()
    state["last_backup_at"] = started
    state["last_backup_status"] = "ok" if all_ok else "error"
    save_state(state)

    return {"ok": all_ok, "results": results, "started_at": started}


# ─── Scheduler ──────────────────────────────────────────────────
async def scheduler_loop():
    """
    Toutes les minutes : vérifie si un backup doit tourner.
    Simple mais efficace : déclenche à `schedule_hour` si aucun backup
    n'a tourné dans les 12 dernières heures.
    """
    await asyncio.sleep(30)  # laisse le temps au démarrage
    while True:
        try:
            cfg = load_config()
            if cfg and cfg.initialized:
                now = datetime.now()
                state = load_state()
                last_at = state.get("last_backup_at")
                should_run = now.hour == cfg.schedule_hour and now.minute < 5
                if should_run:
                    if not last_at:
                        await _run_backup(cfg, tag="auto")
                    else:
                        last = datetime.fromisoformat(last_at)
                        if now - last > timedelta(hours=12):
                            await _run_backup(cfg, tag="auto")
        except Exception as e:
            print(f"[scheduler] erreur : {e}", flush=True)
        await asyncio.sleep(60)


@app.on_event("startup")
async def startup():
    print("=" * 60, flush=True)
    print(" Sérénia Agent v0.1.0 démarré", flush=True)
    print(f" WebUI : http://<votre-nas>:{os.environ.get('SERENIA_PORT', '8765')}", flush=True)
    print("=" * 60, flush=True)
    asyncio.create_task(scheduler_loop())


# ─── API : ajouter une source ────────────────────────────────────
class SourcePayload(BaseModel):
    path: str

@app.post("/api/add-source")
def add_source(p: SourcePayload, _auth=AuthDep):
    cfg = load_config()
    if not cfg:
        raise HTTPException(400, "Non configuré")
    path = p.path.strip()
    if not path:
        return {"ok": False, "error": "Chemin vide"}
    if path in cfg.sources:
        return {"ok": False, "error": "Cette source est déjà ajoutée"}
    if not Path(path).exists():
        return {"ok": False, "error": f"Chemin introuvable sur le NAS : {path}"}
    cfg.sources.append(path)
    save_config(cfg)
    return {"ok": True}


# ─── API : retirer une source ────────────────────────────────────
@app.post("/api/remove-source")
def remove_source(p: SourcePayload, _auth=AuthDep):
    cfg = load_config()
    if not cfg:
        raise HTTPException(400, "Non configuré")
    cfg.sources = [s for s in cfg.sources if s != p.path]
    save_config(cfg)
    return {"ok": True}
