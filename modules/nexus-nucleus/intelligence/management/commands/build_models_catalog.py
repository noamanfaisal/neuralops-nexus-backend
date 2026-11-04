"""
manage.py build_models_catalog -- make a new models.json (release tooling).

    python manage.py build_models_catalog --out /tmp/models.json

For each provider that has a model with a stored key on THIS server, read the
provider's own models list and keep only ids that answer a one-word chat the
way the engine calls them (--no-probe skips that, a few tokens per id). A
provider without a key keeps the previous file's list (or the overrides'
`fallback`). Sizes come from the price table; curated marks from
intelligence/data/models_catalog_overrides.json. Writes the file and
<file>.sha256 -- publish BOTH next to install.sh (catalog/models.json), and
copy the file over intelligence/data/models_catalog.json for the next image.

Keys are read here, used for these calls only, and never printed.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from intelligence import models_catalog as mc


class Command(BaseCommand):
    help = "Build a new model catalog (models.json + .sha256) from each provider's own models list."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="Where to write models.json (the .sha256 goes next to it).")
        parser.add_argument("--previous", help="The catalog to start from (default: the one built into this image).")
        parser.add_argument("--no-probe", action="store_true", help="Trust the providers' lists without a test call per id.")

    def handle(self, *args, **opts):
        import httpx

        from nucleus.models import ModelConfig, ModelPrice

        previous = json.loads(Path(opts["previous"]).read_text()) if opts.get("previous") else mc.bundled()
        overrides = json.loads(mc.OVERRIDES.read_text())

        def get_json(url, headers):
            r = httpx.get(url, headers=headers, timeout=30.0)
            r.raise_for_status()
            return r.json()

        def post_status(url, headers, body):
            try:
                return httpx.post(url, headers=headers, json=body, timeout=60.0).status_code
            except httpx.HTTPError:
                return 0

        live: dict = {}
        for provider in mc.PROVIDERS:
            cfg = (ModelConfig.objects.filter(provider=provider, is_active=True)
                   .exclude(api_key_encrypted="").first())
            key = cfg.get_api_key() if cfg else None
            if not key:
                self.stdout.write(f"{provider}: no key here -- keeping the previous list")
                continue
            try:
                pairs = mc.provider_ids(provider, key, get_json)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(f"{provider}: list failed ({type(exc).__name__}) -- keeping the previous list")
                continue
            hidden = set(overrides.get(provider, {}).get("hidden", []))
            if not opts["no_probe"]:
                kept = []
                for model_id, label in pairs:
                    if model_id in hidden:
                        continue
                    ok = mc.probe(provider, key, model_id, post_status)
                    self.stdout.write(f"  {provider} {model_id}: {'ok' if ok else 'refused -- left out'}")
                    if ok:
                        kept.append((model_id, label))
                pairs = kept
            live[provider] = pairs

        def sizes(provider, model_id):
            row = ModelPrice.objects.filter(provider=provider, model_id=model_id).first()
            return (row.context_window, row.max_output_tokens) if row else (None, None)

        today = timezone.now().date().isoformat()
        try:
            catalog = mc.build(previous=previous, overrides=overrides, live=live, sizes=sizes, today=today)
        except mc.CatalogError as exc:
            raise CommandError(str(exc)) from exc
        raw, sha = mc.dump(catalog)
        out = Path(opts["out"])
        out.write_bytes(raw)
        Path(str(out) + ".sha256").write_text(sha + "\n")
        counts = ", ".join(f"{p} {len(catalog['providers'][p])}" for p in mc.PROVIDERS)
        self.stdout.write(self.style.SUCCESS(f"catalog {catalog['version']} written ({counts}); sha256 {sha}"))
