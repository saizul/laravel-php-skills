import shutil
import subprocess

import pytest

from conftest import load_script, run_script

SKILL = "laravel-deploy-vps"
SCRIPT = "gen_deploy.py"
mod = load_script(SKILL, SCRIPT)
BASE_ARGS = ["--app", "shop", "--domain", "shop.example.com", "--repo", "git@github.com:acme/shop.git"]


def gen(tmp_path, *extra):
    out = tmp_path / "out"
    r = run_script(SKILL, SCRIPT, *BASE_ARGS, "--out", str(out), *extra)
    return r, out


def test_worker_layout(tmp_path):
    r, out = gen(tmp_path)
    assert r.returncode == 0, r.stderr
    names = sorted(p.name for p in out.iterdir())
    assert names == [
        "INSTALL.md",
        "cron-shop",
        "deploy.sh",
        "nginx-shop.conf",
        "rollback.sh",
        "sudoers-shop",
        "supervisor-shop.conf",
    ]
    deploy = (out / "deploy.sh").read_text()
    for needle in [
        'BASE="/var/www/shop"',
        "composer install --no-dev --optimize-autoloader",
        "php artisan migrate --force",
        "php artisan optimize",
        'mv -Tf "$BASE/current.tmp" "$BASE/current"',
        'sudo /usr/bin/systemctl reload "$PHP_FPM"',
        "php artisan queue:restart",
        "npm run build",
        "https://shop.example.com/up",
    ]:
        assert needle in deploy, needle
    # migrations and caches happen before the switch, worker restart after
    assert deploy.index("migrate --force") < deploy.index("mv -Tf") < deploy.index("queue:restart")
    assert (out / "deploy.sh").stat().st_mode & 0o111
    nginx = (out / "nginx-shop.conf").read_text()
    assert "root /var/www/shop/current/public;" in nginx
    assert "$realpath_root$fastcgi_script_name" in nginx
    assert "unix:/run/php/php8.3-fpm.sock" in nginx
    sup = (out / "supervisor-shop.conf").read_text()
    assert "queue:work" in sup and "numprocs=2" in sup and "user=deploy" in sup and "stopwaitsecs=3600" in sup
    assert "* * * * * deploy cd /var/www/shop/current && php artisan schedule:run" in (out / "cron-shop").read_text()
    assert "NOPASSWD: /usr/bin/systemctl reload php8.3-fpm" in (out / "sudoers-shop").read_text()


def test_horizon_and_options(tmp_path):
    r, out = gen(
        tmp_path,
        "--queue",
        "horizon",
        "--php",
        "8.4",
        "--no-assets",
        "--no-migrate",
        "--base",
        "/srv/shop",
        "--keep",
        "3",
    )
    assert r.returncode == 0
    deploy = (out / "deploy.sh").read_text()
    assert "horizon:terminate" in deploy and "npm" not in deploy.split("set -euo")[1].split('log "Running')[0]
    assert "migrate --force" not in deploy and "KEEP=3" in deploy and 'PHP_FPM="php8.4-fpm"' in deploy
    sup = (out / "supervisor-shop.conf").read_text()
    assert "artisan horizon" in sup and "queue:work" not in sup and "/srv/shop/current" in sup


def test_no_queue(tmp_path):
    r, out = gen(tmp_path, "--queue", "none")
    assert r.returncode == 0
    assert not (out / "supervisor-shop.conf").exists()
    assert "supervisorctl" not in (out / "sudoers-shop").read_text()
    assert "Queue workers" not in (out / "INSTALL.md").read_text()


def test_refuses_to_overwrite(tmp_path):
    assert gen(tmp_path)[0].returncode == 0
    r, _ = gen(tmp_path)
    assert r.returncode == 2 and "already exist" in r.stderr
    assert gen(tmp_path, "--force")[0].returncode == 0


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--domain", "shop.example.com; rm -rf /"),
        ("--app", "Shop App"),
        ("--repo", "git@github.com:acme/shop.git && curl x"),
        ("--branch", "main;id"),
        ("--php", "8"),
        ("--user", "Deploy User"),
        ("--base", "/var/www/../etc"),
        ("--base", "relative/path"),
        ("--keep", "0"),
        ("--workers", "100"),
    ],
)
def test_rejects_unsafe_values(tmp_path, flag, value):
    args = list(BASE_ARGS)
    if flag in args:
        args[args.index(flag) + 1] = value
    else:
        args += [flag, value]
    r = run_script(SKILL, SCRIPT, *args, "--print")
    assert r.returncode == 2 and "error:" in r.stderr


def test_print_mode(tmp_path):
    r = run_script(SKILL, SCRIPT, *BASE_ARGS, "--print")
    assert r.returncode == 0 and "===== deploy.sh =====" in r.stdout and "===== INSTALL.md =====" in r.stdout
    assert not list(tmp_path.iterdir())


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
@pytest.mark.parametrize("queue", ["worker", "horizon", "none"])
def test_generated_scripts_parse(tmp_path, queue):
    r, out = gen(tmp_path, "--queue", queue)
    assert r.returncode == 0
    for name in ("deploy.sh", "rollback.sh"):
        check = subprocess.run(["bash", "-n", str(out / name)], capture_output=True, text=True, check=False)
        assert check.returncode == 0, check.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_generated_scripts_pass_shellcheck(tmp_path):
    _, out = gen(tmp_path)
    check = subprocess.run(
        ["shellcheck", str(out / "deploy.sh"), str(out / "rollback.sh")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert check.returncode == 0, check.stdout


def test_build_is_deterministic():
    c = {
        "app": "a",
        "domain": "a.example.com",
        "repo": "https://github.com/x/a.git",
        "branch": "main",
        "base": "/var/www/a",
        "php": "8.3",
        "user": "deploy",
        "web_group": "www-data",
        "queue": "worker",
        "workers": 1,
        "keep": 5,
        "assets": True,
        "migrate": True,
    }
    assert mod.build(c) == mod.build(dict(c))


def test_help_and_required_args():
    assert run_script(SKILL, SCRIPT, "--help").returncode == 0
    assert run_script(SKILL, SCRIPT, "--app", "x").returncode == 2
    assert run_script(SKILL, SCRIPT, *BASE_ARGS).returncode == 2  # needs --out or --print
